import http.server, socketserver, functools, os
D = os.path.dirname(os.path.abspath(__file__))
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=D)
socketserver.TCPServer.allow_reuse_address = True
print("serving", D, "on 8001")
socketserver.TCPServer(("127.0.0.1", 8001), H).serve_forever()
