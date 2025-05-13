using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Diagnostics;

class P2PChat
{
    static UdpClient udpClient;
    static TcpListener tcpListener;
    static List<TcpClient> peers = new List<TcpClient>();
    static string userName;
    static HashSet<string> receivedMessages = new HashSet<string>();
    static List<string> story = new List<string>();
    static int udpPort = 8888;
    static int tcpPort;
    static IPAddress localIP;
    static string selfIdentifier;


    static void Main(string[] args)
    {
        //args = new string[] { "user1", "127.0.0.1" };
        if (args.Length < 2)
        {
            Console.WriteLine("Использование: P2PChat.exe <имя> <IP-адрес>");
            return;
        }

        userName = args[0];
        if (!IPAddress.TryParse(args[1], out localIP))
        {
            Console.WriteLine("Неверный IP-адрес");
            return;
        }
        tcpPort = new Random().Next(8000, 9000);
        selfIdentifier = $"{localIP}:{tcpPort}";
        StartUdpListener();
        StartTcpListener();

        BroadcastPresence();

        Console.WriteLine("Вы подключились");
        story.Add("[Входящие] Вы подключились");
        SetConsoleCtrlHandler(new ConsoleCtrlDelegate(ConsoleClosing), true);

        while (true)
        {
            string message = Console.ReadLine();
            if (message.ToLower() == "история")
            {
                ShowHistory(story);
                continue;
            }
            if (message == "send")
            {
                string listToString = $"{userName} [story]:" + JsonConvert.SerializeObject(story);
                SendMessageToPeers(listToString);
                continue;
            }
            string formattedMessage = $"{DateTime.Now:dd.MM.yyyy HH:mm:ss}: {userName}: {message}";
            Console.WriteLine(formattedMessage);
            story.Add("[Исходящие] " + formattedMessage);
            SendMessageToPeers(formattedMessage);
        }
    }

    static void ShowHistory(List<string> story)
    {
        Console.WriteLine("\nИстория сообщений:");
        Console.WriteLine("====================");
        Console.WriteLine("[Исходящие]");
        foreach (var msg in story.Where(m => m.StartsWith("[Исходящие]")))
        {
            Console.WriteLine(msg.Substring(13));
        }
        Console.WriteLine("\n[Входящие]");
        foreach (var msg in story.Where(m => m.StartsWith("[Входящие]")))
        {
            Console.WriteLine(msg.Substring(11));
        }
        Console.WriteLine("====================\n");
    }

    [System.Runtime.InteropServices.DllImport("Kernel32")]
    private static extern bool SetConsoleCtrlHandler(ConsoleCtrlDelegate handler, bool add);

    private delegate bool ConsoleCtrlDelegate(int sig);

    private static bool ConsoleClosing(int sig)
    {
        Disconnect();
        return false;
    }


    static void Disconnect()
    {
        string exitMessage = $"[EXIT] {userName}";

        try
        {
            Console.WriteLine(exitMessage);


            foreach (var peer in new List<TcpClient>(peers))
            {
                try
                {
                    if (peer.Connected)
                    {
                        NetworkStream stream = peer.GetStream();
                        byte[] exitData = Encoding.UTF8.GetBytes(exitMessage + "\n");


                        stream.Write(exitData, 0, exitData.Length);

                        stream.Flush();
                    }
                }
                catch
                {

                }
                //peer.Close();
            }


            //peers.Clear();
            //Thread.Sleep(1000);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Ошибка при выходе: {ex.Message}");
        }
        finally
        {


            udpClient?.Close();
            tcpListener?.Stop();
        }
    }


    static void StartUdpListener()
    {
        try
        {
            udpClient = new UdpClient();
            udpClient.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
            udpClient.Client.Bind(new IPEndPoint(localIP, udpPort));

            Thread udpThread = new Thread(() =>
            {
                while (true)
                {
                    IPEndPoint remoteEP = new IPEndPoint(IPAddress.Any, 0);
                    byte[] data = udpClient.Receive(ref remoteEP);
                    string receivedData = Encoding.UTF8.GetString(data);


                    if (remoteEP.Address.Equals(localIP))
                    {
                        //Console.WriteLine("Игнорируем собственный broadcast");
                        continue;
                    }
                    string[] strings = receivedData.Split(':');
                    string ip = strings[1];
                    int port = int.Parse(strings[2]);
                    string username = strings[0];

                    ConnectToPeer(ip, port);
                }
            });
            udpThread.IsBackground = true;
            udpThread.Start();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Ошибка UDP: {ex.Message}");
        }
    }



    static void BroadcastPresence()
    {
        try
        {
            using (UdpClient client = new UdpClient(new IPEndPoint(localIP, 0)))
            {
                client.EnableBroadcast = true;
                string message = $"{userName}:{localIP}:{tcpPort}";
                byte[] data = Encoding.UTF8.GetBytes(message);


                IPEndPoint broadcastEP = new IPEndPoint(/*IPAddress.Parse("127.255.255.255")*/IPAddress.Broadcast, udpPort);
                client.Send(data, data.Length, broadcastEP);


            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Ошибка широковещания: {ex.Message}");
        }
    }

    static void StartTcpListener()
    {
        try
        {
            tcpListener = new TcpListener(localIP, tcpPort);
            tcpListener.Start();
            // Console.WriteLine($"TCP слушает на {((IPEndPoint)tcpListener.LocalEndpoint).Address}:{((IPEndPoint)tcpListener.LocalEndpoint).Port}");
            Thread tcpThread = new Thread(() =>
            {
                while (true)
                {
                    TcpClient client = tcpListener.AcceptTcpClient();
                    // var remoteEP = (IPEndPoint)client.Client.RemoteEndPoint;
                    peers.Add(client);
                    SendMessageToPeers($"Пользователь {userName} подключился");
                    Thread clientThread = new Thread(() => HandleClient(client));
                    clientThread.IsBackground = true;
                    clientThread.Start();
                }
            });
            tcpThread.IsBackground = true;
            tcpThread.Start();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Ошибка TCP: {ex.Message}");
        }
    }

    static void ConnectToPeer(string ipAddress, int peerTcpPort)
    {
        TcpClient client = new TcpClient(ipAddress, peerTcpPort);
        peers.Add(client);

        SendMessageToPeers($"Пользователь {userName} подключился");

        Thread clientThread = new Thread(() => HandleClient(client));
        clientThread.IsBackground = true;
        clientThread.Start();
    }




    static void HandleClient(TcpClient client)
    {

        NetworkStream stream = client.GetStream();
        StreamReader reader = new StreamReader(stream, Encoding.UTF8);


        try
        {
            while (client.Connected)
            {
                string message = reader.ReadLine();
                Debugger.Break();
                if (message != null && !message.Contains(userName) || message.Contains("[story]"))
                {
                    //if (receivedMessages.Contains(message))
                    //{
                    //    continue;
                    //}
                    if (message.StartsWith("Пользователь ") && message.EndsWith(" подключился"))
                    {
                        if (!receivedMessages.Contains(message))
                        {
                            receivedMessages.Add(message);
                            story.Add("[Входящие] " + message);
                            Console.WriteLine(message);
                            SendMessageToPeers(message);
                        }
                    }
                    else if (message.Contains("[story]"))
                    {

                        int index = message.IndexOf('[');
                        string name = message.Substring(0, index - 1);
                        if (userName != name)
                        {
                            Console.WriteLine($"Получена история от {name}");
                            int indexTwoPoint = message.IndexOf(':');

                            List<string> otherStory = JsonConvert.DeserializeObject<List<string>>(message.Substring(indexTwoPoint + 1));
                            ShowHistory(otherStory);
                        }

                    }
                    else if (message.StartsWith("[EXIT]"))
                    {
                        string exitedUser = message.Substring(7);
                        string deleteMessage = receivedMessages.FirstOrDefault(x => x.Contains(exitedUser));
                        receivedMessages.Remove(deleteMessage);
                        string exitMsg = $"Пользователь {exitedUser} вышел";
                        story.Add("[Входящие] " + exitMsg);
                        Console.WriteLine(exitMsg);
                    }
                    else
                    {
                        receivedMessages.Add(message);
                        story.Add("[Входящие] " + message);
                        Console.WriteLine(message);
                        //SendMessageToPeers(message);
                    }
                }

            }
        }
        catch
        {
            client.Close();
            peers.Remove(client);
        }
    }

    static void SendMessageToPeers(string message)
    {
        byte[] data = Encoding.UTF8.GetBytes(message + "\n");
        foreach (var peer in peers.ToList())
        {
            try
            {
                if (((IPEndPoint)peer.Client.RemoteEndPoint).Port != tcpPort)
                {
                    peer.GetStream().Write(data, 0, data.Length);

                }
            }
            catch
            {
                peers.Remove(peer);
            }
        }
    }


}
