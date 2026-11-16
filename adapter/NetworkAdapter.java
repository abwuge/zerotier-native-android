package org.zerotier.nativeandroid;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.EthernetNetworkSpecifier;
import android.net.IpPrefix;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.NetworkAgent;
import android.net.NetworkAgentConfig;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.RouteInfo;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Publishes daemon-owned interfaces without configuring their addresses. */
public final class NetworkAdapter {
    private final Context context;
    private final ConnectivityManager connectivity;
    private final Handler handler;
    private final Map<String, PublishedNetwork> networks = new HashMap<>();
    private final Process monitor;
    private volatile boolean closing;
    private final Runnable update = () -> {
        try {
            reconcile();
        } catch (Exception error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    };

    private NetworkAdapter(Context context) throws IOException {
        this.context = context;
        connectivity = context.getSystemService(ConnectivityManager.class);
        handler = new Handler(Looper.getMainLooper());
        // Subscribe before the first snapshot; the reader coalesces queued events.
        monitor = new ProcessBuilder("/system/bin/ip", "-o", "monitor", "link", "address", "route")
                .redirectError(ProcessBuilder.Redirect.INHERIT).start();
    }

    public static void main(String[] args) {
        try {
            Looper.prepareMainLooper();
            Class<?> activityThread = Class.forName("android.app.ActivityThread");
            Object thread = activityThread.getMethod("systemMain").invoke(null);
            Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
            NetworkAdapter adapter = new NetworkAdapter(context);
            Runtime.getRuntime().addShutdownHook(new Thread(adapter::close, "network-cleanup"));
            adapter.start();
            Looper.loop();
        } catch (Throwable error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private void start() {
        handler.post(update);
        new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(monitor.getInputStream()))) {
                while (reader.readLine() != null) {
                    handler.removeCallbacks(update);
                    handler.postDelayed(update, 100);
                }
                if (!closing) {
                    throw new IOException("The network event monitor stopped");
                }
            } catch (IOException error) {
                if (!closing) {
                    error.printStackTrace(System.err);
                    System.exit(1);
                }
            }
        }, "network-events").start();
    }

    private synchronized void reconcile() throws Exception {
        Set<String> present = new HashSet<>();
        for (NetworkInterface iface : Collections.list(NetworkInterface.getNetworkInterfaces())) {
            String name = iface.getName();
            if (!name.matches("zt[0-9a-z]+") || !iface.isUp()) {
                continue;
            }
            LinkProperties properties;
            try {
                properties = properties(iface);
            } catch (IOException error) {
                NetworkInterface current = NetworkInterface.getByName(name);
                if (current == null || current.getIndex() != iface.getIndex() || !current.isUp()) {
                    continue;
                }
                throw error;
            }
            if (properties == null) {
                continue;
            }
            present.add(name);
            PublishedNetwork published = networks.get(name);
            if (published != null && published.interfaceIndex != iface.getIndex()) {
                networks.remove(name).close();
                published = null;
            }
            if (published == null) {
                networks.put(name, new PublishedNetwork(iface, properties));
            } else if (!published.properties.equals(properties)) {
                published.agent.sendLinkProperties(properties);
                published.properties = properties;
            }
        }
        for (String name : new ArrayList<>(networks.keySet())) {
            if (!present.contains(name)) {
                networks.remove(name).close();
            }
        }
    }

    private static LinkProperties properties(NetworkInterface iface) throws Exception {
        LinkProperties properties = new LinkProperties();
        properties.setInterfaceName(iface.getName());
        properties.setMtu(iface.getMTU());
        boolean addressed = false;
        for (InterfaceAddress address : iface.getInterfaceAddresses()) {
            InetAddress ip = address.getAddress();
            properties.addLinkAddress(new LinkAddress(ip, address.getNetworkPrefixLength()));
            addressed |= !ip.isLinkLocalAddress();
        }
        if (!addressed) {
            return null;
        }
        for (String family : new String[]{"-4", "-6"}) {
            for (String line : readRoutes(family, iface.getName())) {
                String[] words = line.trim().split("\\s+");
                if (line.contains("linkdown") || words[0].isEmpty()) {
                    continue;
                }
                String destination = words[0];
                if (destination.equals("default")) {
                    destination = family.equals("-4") ? "0.0.0.0/0" : "::/0";
                } else if (!destination.contains("/")) {
                    destination += family.equals("-4") ? "/32" : "/128";
                }
                InetAddress gateway = null;
                for (int i = 1; i + 1 < words.length; i++) {
                    if (words[i].equals("via")) {
                        gateway = InetAddress.getByName(words[++i]);
                    }
                }
                properties.addRoute(new RouteInfo(new IpPrefix(destination), gateway,
                        iface.getName(), RouteInfo.RTN_UNICAST));
            }
        }
        return properties;
    }

    private static List<String> readRoutes(String family, String name) throws Exception {
        Process process = new ProcessBuilder("/system/bin/ip", family, "-o", "route", "show",
                "table", "main", "dev", name).redirectError(ProcessBuilder.Redirect.INHERIT).start();
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
            String line;
            while ((line = reader.readLine()) != null) {
                lines.add(line);
            }
        }
        if (process.waitFor() != 0) {
            throw new IOException("Could not read routes for " + name);
        }
        return lines;
    }

    private synchronized void close() {
        closing = true;
        handler.removeCallbacks(update);
        monitor.destroy();
        for (PublishedNetwork network : networks.values()) {
            network.close();
        }
        networks.clear();
    }

    private final class PublishedNetwork {
        private final NetworkAgent agent;
        private final ConnectivityManager.NetworkCallback request;
        private final int interfaceIndex;
        private LinkProperties properties;

        PublishedNetwork(NetworkInterface iface, LinkProperties properties) {
            String name = iface.getName();
            interfaceIndex = iface.getIndex();
            this.properties = properties;
            EthernetNetworkSpecifier specifier = new EthernetNetworkSpecifier(name);
            NetworkCapabilities.Builder capabilities = new NetworkCapabilities.Builder()
                    .addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET)
                    .setNetworkSpecifier(specifier);
            if (Build.VERSION.SDK_INT >= 31) {
                capabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VCN_MANAGED);
            }
            NetworkAgentConfig config = new NetworkAgentConfig.Builder()
                    .setLegacyType(ConnectivityManager.TYPE_ETHERNET)
                    .setLegacyTypeName("ETHERNET")
                    .setLegacyExtraInfo(name).build();
            agent = new NetworkAgent(context, Looper.getMainLooper(), "ZeroTierNative",
                    capabilities.build(), properties, 0, config, null) {};
            request = new ConnectivityManager.NetworkCallback();
            // A local-only request retains the network without making it an Internet default.
            connectivity.requestNetwork(new NetworkRequest.Builder()
                    .addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET)
                    .setNetworkSpecifier(specifier).build(), request);
            try {
                agent.register();
                agent.markConnected();
            } catch (RuntimeException error) {
                connectivity.unregisterNetworkCallback(request);
                throw error;
            }
            System.out.println("Registered Android network for " + name);
        }

        void close() {
            agent.unregister();
            connectivity.unregisterNetworkCallback(request);
        }
    }
}
