using System.Net;
using System.Net.Sockets;
using System.Text;

class ProxyServer
{
    private const int ProxyPort = 8888;
    private const int BufferSize = 8192;
    private const int DefaultHttpPort = 80;

    static async Task Main()
    {
        var listener = new TcpListener(IPAddress.Any, ProxyPort);
        listener.Start();

        Console.WriteLine($"[*] Прокси-сервер запущен на порту {ProxyPort}");

        try
        {
            while (true)
            {
                var client = await listener.AcceptTcpClientAsync();
                _ = HandleClientAsync(client);
            }
        }
        finally
        {
            listener.Stop();
        }
    }

    private static async Task HandleClientAsync(TcpClient client)
    {
        string requestUrl = null;
        string statusCode = null;
        Uri targetUri = null;

        try
        {
            using (client)
            using (var clientStream = client.GetStream())
            {
                var buffer = new byte[BufferSize];
                int bytesRead = await clientStream.ReadAsync(buffer, 0, buffer.Length);
                if (bytesRead == 0) return;

                string request = Encoding.ASCII.GetString(buffer, 0, bytesRead);
                var firstLine = request.Split('\n')[0];
                var parts = firstLine.Split(' ');

                if (parts.Length < 3) return;

                string method = parts[0];
                requestUrl = parts[1];
                string httpVersion = parts[2].Trim();

                if (!requestUrl.StartsWith("http://") && !requestUrl.StartsWith("https://"))
                {
                    if (requestUrl.StartsWith("/"))
                        requestUrl = "http:/" + requestUrl;
                    else
                        return;
                }

                if (!Uri.TryCreate(requestUrl, UriKind.Absolute, out targetUri))
                    return;

                string host = targetUri.Host;
                int port = targetUri.Port == -1 ? DefaultHttpPort : targetUri.Port;
                string path = targetUri.PathAndQuery;

                using (var server = new TcpClient())
                {
                    await server.ConnectAsync(host, port);
                    using (var serverStream = server.GetStream())
                    {
                        var requestBuilder = new StringBuilder();
                        requestBuilder.AppendLine($"{method} {path} {httpVersion}");
                        requestBuilder.AppendLine($"Host: {host}");
                        requestBuilder.AppendLine("Connection: close");

                        if (method.Equals("POST", StringComparison.OrdinalIgnoreCase))
                        {
                            requestBuilder.AppendLine("Content-Type: application/x-www-form-urlencoded");
                            requestBuilder.AppendLine("Content-Length: 0");
                        }
                        requestBuilder.AppendLine();

                        byte[] requestBytes = Encoding.ASCII.GetBytes(requestBuilder.ToString());
                        await serverStream.WriteAsync(requestBytes, 0, requestBytes.Length);

                        bool headersComplete = false;
                        var responseBuffer = new byte[BufferSize];
                        var responseMemory = new MemoryStream();

                        while (true)
                        {
                            int read = await serverStream.ReadAsync(responseBuffer, 0, responseBuffer.Length);
                            if (read == 0) break;

                            await responseMemory.WriteAsync(responseBuffer, 0, read);

                            if (!headersComplete)
                            {
                                string responseText = Encoding.ASCII.GetString(responseMemory.ToArray());
                                int headerEnd = responseText.IndexOf("\r\n\r\n");
                                if (headerEnd >= 0)
                                {
                                    headersComplete = true;
                                    var statusLine = responseText.Substring(0, responseText.IndexOf('\n'));
                                    statusCode = statusLine.Split(' ')[1];

                                    if (!ShouldFilterRequest(targetUri, path))
                                    {
                                        Console.WriteLine($"{requestUrl} - {statusCode}");
                                    }
                                }
                            }

                            try
                            {
                                await clientStream.WriteAsync(responseBuffer, 0, read);
                            }
                            catch { break; }
                        }
                    }
                }
            }
        }
        catch (Exception ex) when (IsConnectionError(ex))
        {
            if (requestUrl != null && targetUri != null && !ShouldFilterRequest(targetUri, requestUrl))
                Console.WriteLine($"{requestUrl} - ERROR: Соединение разорвано");
        }
        catch (Exception ex)
        {
            if (requestUrl != null && targetUri != null && !ShouldFilterRequest(targetUri, requestUrl)) ;
        }
    }

    private static bool ShouldFilterRequest(Uri uri, string path)
    {
        return uri.Host.Contains("googleapis.com") ||
               path.EndsWith("favicon.ico", StringComparison.OrdinalIgnoreCase);
    }

    private static bool IsConnectionError(Exception ex)
    {
        return ex is IOException || ex is SocketException;
    }
}