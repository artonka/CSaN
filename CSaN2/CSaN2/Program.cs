using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

class Program
{
    const int MAX_HOPS = 30;
    const int TRIES = 3;
    const int TIMEOUT = 3000;

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    struct IcmpHeader
    {
        public byte Type;
        public byte Code;
        public ushort Checksum;
        public ushort Id;
        public ushort Sequence;
    }

    static ushort CalculateChecksum(byte[] buffer, int size)
    {
        int sum = 0;
        int i = 0;
        while (size > 1)
        {
            sum += BitConverter.ToUInt16(buffer, i);
            i += 2;
            size -= 2;
        }
        if (size == 1)
        {
            sum += buffer[i];
        }
        sum = (sum >> 16) + (sum & 0xFFFF);
        sum += (sum >> 16);
        return (ushort)~sum;
    }

    static void Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.Write("Аналог утилиты traceroute / tracert\n\n");
        Console.Write("Введите домен или IP-адрес: ");
        string target = Console.ReadLine();

        IPAddress ipAddress;
        try
        {
            ipAddress = Dns.GetHostEntry(target).AddressList[0];
        }
        catch
        {
            Console.WriteLine("Не удалось разрешить адрес.");
            return;
        }

        Console.WriteLine($"\nТрассировка маршрута к {target} [{ipAddress}], максимальное число прыжков: {MAX_HOPS}\n");

        using (Socket socket = new Socket(AddressFamily.InterNetwork, SocketType.Raw, ProtocolType.Icmp))
        {
            socket.ReceiveTimeout = TIMEOUT;

            ushort processId = (ushort)Process.GetCurrentProcess().Id;

            bool reached = false;

            for (int ttl = 1; ttl <= MAX_HOPS && !reached; ttl++)
            {
                socket.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.IpTimeToLive, ttl);
                Console.Write($"{ttl}\t");

                bool gotAnyReply = false;
                string lastReplyIp = "";
                string lastHost = "";

                for (int i = 0; i < TRIES; i++)
                {
                    byte[] packet = new byte[Marshal.SizeOf<IcmpHeader>() + 4];
                    IcmpHeader header = new IcmpHeader
                    {
                        Type = 8,
                        Code = 0,
                        Id = (ushort)IPAddress.HostToNetworkOrder((short)processId),
                        Sequence = (ushort)IPAddress.HostToNetworkOrder((short)(ttl * 100 + i)),
                        Checksum = 0
                    };

                    IntPtr ptr = Marshal.AllocHGlobal(packet.Length);
                    Marshal.StructureToPtr(header, ptr, false);
                    Marshal.Copy(ptr, packet, 0, Marshal.SizeOf<IcmpHeader>());
                    Marshal.FreeHGlobal(ptr);

                    header.Checksum = CalculateChecksum(packet, packet.Length);

                    ptr = Marshal.AllocHGlobal(packet.Length);
                    Marshal.StructureToPtr(header, ptr, false);
                    Marshal.Copy(ptr, packet, 0, Marshal.SizeOf<IcmpHeader>());
                    Marshal.FreeHGlobal(ptr);

                    EndPoint remoteEndPoint = new IPEndPoint(ipAddress, 0);
                    Stopwatch stopwatch = Stopwatch.StartNew();

                    try
                    {
                        socket.SendTo(packet, remoteEndPoint);
                        byte[] buffer = new byte[1024];
                        EndPoint sender = new IPEndPoint(IPAddress.Any, 0);
                        int received = socket.ReceiveFrom(buffer, ref sender);
                        stopwatch.Stop();

                        gotAnyReply = true;

                        IPEndPoint remote = (IPEndPoint)sender;
                        lastReplyIp = remote.Address.ToString();

                        try
                        {
                            lastHost = Dns.GetHostEntry(remote.Address).HostName;
                        }
                        catch { }

                        Console.Write($"{stopwatch.ElapsedMilliseconds} ms\t");

                        int ipHeaderLength = (buffer[0] & 0x0F) * 4;
                        byte icmpType = buffer[ipHeaderLength];
                        if (icmpType == 0)
                        {
                            reached = true;
                        }
                    }
                    catch
                    {
                        Console.Write("*\t");
                    }
                }

                if (gotAnyReply)
                {
                    if (!string.IsNullOrEmpty(lastHost))
                        Console.WriteLine($"{lastHost} [{lastReplyIp}]");
                    else
                        Console.WriteLine(lastReplyIp);
                }
                else
                {
                    Console.WriteLine("Превышен интервал ожидания для запроса.");
                }
            }
        }
        Console.WriteLine("\nТрассировка завершена.");
        Console.ReadKey();
    }
}