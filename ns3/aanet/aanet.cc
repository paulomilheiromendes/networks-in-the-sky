// Example ns-3 scenario for the "Networks in the Sky" template.
//
// A snapshot of an aeronautical ad-hoc network (AANET): aircraft are placed
// uniformly at random in a square area. Every pair closer than commRange gets
// an air-to-air point-to-point link whose propagation delay is distance / c.
// Shortest-path (min-hop) routing is computed globally, then numFlows random
// source/destination pairs exchange CBR UDP traffic. Per-flow results are
// written to a CSV file (one row per flow).
//
// Replace this with your own scenario, but keep the command-line contract:
//   --outFile=<path>   where the CSV is written (required by the notebook)
//   --RngRun=<k>       ns-3 global value selecting the random stream
//
// Example:
//   ./ns3 run "aanet --numNodes=50 --commRange=300000 --RngRun=1 --outFile=out.csv"

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"

#include <cmath>
#include <fstream>
#include <limits>
#include <map>
#include <queue>
#include <vector>

using namespace ns3;

namespace
{

// Breadth-first search: hop count from src to every node (-1 = unreachable).
std::vector<int>
HopCounts(const std::vector<std::vector<uint32_t>>& adj, uint32_t src)
{
    std::vector<int> hops(adj.size(), -1);
    std::queue<uint32_t> q;
    hops[src] = 0;
    q.push(src);
    while (!q.empty())
    {
        uint32_t u = q.front();
        q.pop();
        for (uint32_t v : adj[u])
        {
            if (hops[v] < 0)
            {
                hops[v] = hops[u] + 1;
                q.push(v);
            }
        }
    }
    return hops;
}

struct Flow
{
    uint32_t src;
    uint32_t dst;
    double distanceKm;
    int hops;
    uint16_t port;
};

} // namespace

int
main(int argc, char* argv[])
{
    uint32_t numNodes = 50;
    double commRange = 300e3; // m, air-to-air communication range
    double areaSize = 1000e3; // m, side of the square area
    double simTime = 10.0;    // s
    uint32_t numFlows = 10;
    std::string linkRate = "100Mbps";
    double interval = 0.01;      // s between packets of one flow (100 pkt/s)
    uint32_t packetSize = 1000;  // bytes
    std::string outFile = "aanet.csv";

    CommandLine cmd(__FILE__);
    cmd.AddValue("numNodes", "Number of aircraft", numNodes);
    cmd.AddValue("commRange", "Air-to-air communication range [m]", commRange);
    cmd.AddValue("areaSize", "Side of the square simulation area [m]", areaSize);
    cmd.AddValue("simTime", "Simulated time [s]", simTime);
    cmd.AddValue("numFlows", "Number of random source/destination flows", numFlows);
    cmd.AddValue("linkRate", "Data rate of each air-to-air link", linkRate);
    cmd.AddValue("interval", "Packet interval per flow [s]", interval);
    cmd.AddValue("packetSize", "UDP payload size [bytes]", packetSize);
    cmd.AddValue("outFile", "Output CSV file", outFile);
    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(numNodes < 2, "numNodes must be >= 2");
    NS_ABORT_MSG_IF(simTime <= 1.0, "simTime must be > 1 s (traffic starts at t=1 s)");

    // --- Aircraft positions (controlled by --RngRun) ---
    Ptr<UniformRandomVariable> uni = CreateObject<UniformRandomVariable>();
    std::vector<std::pair<double, double>> pos(numNodes);
    for (auto& p : pos)
    {
        p.first = uni->GetValue(0.0, areaSize);
        p.second = uni->GetValue(0.0, areaSize);
    }

    NodeContainer nodes;
    nodes.Create(numNodes);
    InternetStackHelper stack;
    stack.Install(nodes);

    // --- Air-to-air links: one point-to-point link per pair within range ---
    const double c = 299792458.0;
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue(linkRate));
    Ipv4AddressHelper address;
    address.SetBase("10.0.0.0", "255.255.255.252");

    std::vector<std::vector<uint32_t>> adj(numNodes);
    uint32_t numLinks = 0;
    for (uint32_t i = 0; i < numNodes; ++i)
    {
        for (uint32_t j = i + 1; j < numNodes; ++j)
        {
            double d = std::hypot(pos[i].first - pos[j].first, pos[i].second - pos[j].second);
            if (d <= commRange)
            {
                p2p.SetChannelAttribute("Delay", TimeValue(Seconds(d / c)));
                NetDeviceContainer dev = p2p.Install(nodes.Get(i), nodes.Get(j));
                address.Assign(dev);
                address.NewNetwork();
                adj[i].push_back(j);
                adj[j].push_back(i);
                ++numLinks;
            }
        }
    }
    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // --- Random flows ---
    std::vector<Flow> flows;
    for (uint32_t f = 0; f < numFlows; ++f)
    {
        uint32_t src = uni->GetInteger(0, numNodes - 1);
        uint32_t dst = uni->GetInteger(0, numNodes - 1);
        while (dst == src)
        {
            dst = uni->GetInteger(0, numNodes - 1);
        }
        double d = std::hypot(pos[src].first - pos[dst].first, pos[src].second - pos[dst].second);
        int hops = HopCounts(adj, src)[dst];
        uint16_t port = 9000 + f;
        flows.push_back({src, dst, d / 1e3, hops, port});

        if (hops < 0)
        {
            continue; // no path: reported as unreachable, no traffic installed
        }
        Ipv4Address dstAddr = nodes.Get(dst)->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();

        UdpServerHelper server(port);
        ApplicationContainer s = server.Install(nodes.Get(dst));
        s.Start(Seconds(0.0));
        s.Stop(Seconds(simTime + 1.0));

        UdpClientHelper client(dstAddr, port);
        client.SetAttribute("MaxPackets", UintegerValue(std::numeric_limits<uint32_t>::max()));
        client.SetAttribute("Interval", TimeValue(Seconds(interval)));
        client.SetAttribute("PacketSize", UintegerValue(packetSize));
        ApplicationContainer a = client.Install(nodes.Get(src));
        a.Start(Seconds(1.0 + 0.001 * f));
        a.Stop(Seconds(simTime));
    }

    FlowMonitorHelper fmHelper;
    Ptr<FlowMonitor> monitor = fmHelper.InstallAll();

    Simulator::Stop(Seconds(simTime + 1.0));
    Simulator::Run();

    // --- Collect per-flow statistics, matched by destination port ---
    monitor->CheckForLostPackets();
    auto classifier = DynamicCast<Ipv4FlowClassifier>(fmHelper.GetClassifier());
    std::map<uint16_t, FlowMonitor::FlowStats> byPort;
    for (const auto& [id, st] : monitor->GetFlowStats())
    {
        byPort[classifier->FindFlow(id).destinationPort] = st;
    }

    std::ofstream out(outFile);
    NS_ABORT_MSG_IF(!out.is_open(), "Cannot open output file " << outFile);
    out << "flow,src,dst,distance_km,hops,reachable,tx_packets,rx_packets,loss_ratio,"
           "mean_delay_ms,throughput_mbps,num_links,mean_degree\n";
    double meanDegree = 2.0 * numLinks / numNodes;
    for (uint32_t f = 0; f < flows.size(); ++f)
    {
        const Flow& fl = flows[f];
        uint64_t tx = 0;
        uint64_t rx = 0;
        double delayMs = std::nan("");
        double thrMbps = 0.0;
        auto it = byPort.find(fl.port);
        if (it != byPort.end())
        {
            const auto& st = it->second;
            tx = st.txPackets;
            rx = st.rxPackets;
            if (rx > 0)
            {
                delayMs = st.delaySum.GetSeconds() / rx * 1e3;
                double dur = (st.timeLastRxPacket - st.timeFirstTxPacket).GetSeconds();
                thrMbps = dur > 0 ? st.rxBytes * 8.0 / dur / 1e6 : 0.0;
            }
        }
        double loss = tx > 0 ? 1.0 - static_cast<double>(rx) / tx : std::nan("");
        out << f << ',' << fl.src << ',' << fl.dst << ',' << fl.distanceKm << ',' << fl.hops << ','
            << (fl.hops >= 0 ? 1 : 0) << ',' << tx << ',' << rx << ',' << loss << ',' << delayMs
            << ',' << thrMbps << ',' << numLinks << ',' << meanDegree << '\n';
    }
    out.close();

    Simulator::Destroy();
    return 0;
}
