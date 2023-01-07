from http import HTTPStatus
from os import environ, listdir, path
from urllib import request, parse
from urllib.request import Request, urlopen
import json, mimetypes, socket, threading

# Load environment variables
env = {}
try:
    with open(".env") as file:
        for line in file.readlines():
            key = ""
            for char in line:
                if char == "=":
                    break
                key += char
            env[key] = line.lstrip(f"{key}=").strip()
except:
    # .env doesn't exist, so just read from system environment variables
    env = dict(environ)

# Make sure all necessary environment variables exist
if not env.get("PORT"):
    raise Exception("Please include the PORT environment variable inside .env")
if not env.get("SPOTIFY_ENCODED_TOKEN"):
    raise Exception(
        "Please include the SPOTIFY_ENCODED_TOKEN environment variable inside .env"
    )
if not env.get("SPOTIFY_REFRESH_TOKEN"):
    raise Exception(
        "Please include the SPOTIFY_REFRESH_TOKEN environment variable inside .env"
    )


# Functions for templating data
def listening_to():
    """Get what I'm listening to on Spotify."""
    data = parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": env["SPOTIFY_REFRESH_TOKEN"]}
    ).encode()

    req = Request("https://accounts.spotify.com/api/token", method="POST", data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Authorization", f"Basic {env['SPOTIFY_ENCODED_TOKEN']}")
    res = json.loads(request.urlopen(req).read())

    # Once we get the Spotify refresh token, use it to get what I'm currently listening to
    req = Request(
        "https://api.spotify.com/v1/me/player/currently-playing", method="GET"
    )
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {res.get('access_token')}")
    res = request.urlopen(req).read()

    song_str = "nothing"
    if len(res):
        data = json.loads(res)
        song_str = f"{data.get('item').get('name')} by {', '.join([artist.get('name') for artist in data.get('item').get('artists')])}"
    return {
        "status_code": 200,
        "content_type": "application/json",
        "body": json.dumps({"value": song_str}),
    }


def get_posts():
    """Get the posts I've made, stored in /posts."""
    posts = []
    for file in listdir("./posts"):
        with open(f"./posts/{file}") as f:
            posts.append({"date": file.strip(".md"), "content": f.read()})
    return json.dumps(sorted(posts, key=lambda x: x["date"].split("-")[::-1]))


data = {"index.html": {"posts": get_posts()}}


class TCPServer:
    host = "0.0.0.0"
    port = int(env["PORT"])
    max_connections = 5  # Max connections in queue

    @classmethod
    def start(cls):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((cls.host, cls.port))
        s.listen(cls.max_connections)

        print("Listening on port", cls.port)

        while True:
            # Accept any new connection
            conn, addr = s.accept()
            conn.settimeout(60)
            threading.Thread(target=cls.handle, args=(conn, addr)).start()

    @classmethod
    def handle(cls, conn, addr):
        data = conn.recv(1024)
        response = cls.handle_request(data)
        print(response)
        conn.sendall(response)
        conn.close()

    def handle_request(self, data):
        """Handle incoming data."""
        pass


class HTTPServer(TCPServer):
    private_files = ["..", "main.py"]  # Add some sense of security
    request_methods = ["GET"]
    api_routes = {"spotify": listening_to}
    status_codes = {}
    for enum in HTTPStatus:
        status_codes[enum.value] = str(enum).lstrip("HTTPStatus.")

    @classmethod
    def handle_request(cls, data):
        request = HTTPRequest(data, cls.request_methods, cls.private_files)

        if request.valid:
            handler = getattr(cls, f"handle_{request.method}")
            response = handler(request)
            return response
        else:
            response_line = cls.response_line(status_code=200)
            response_headers = cls.response_headers({"Content-Type": "text/html"})
            response_body = b"Invalid request method"
            return b"".join([response_line, response_headers, b"\r\n", response_body])

    @classmethod
    def response_line(cls, status_code):
        reason = cls.status_codes.get(status_code)
        line = f"HTTP/1.1 {status_code} {reason}\r"
        return line.encode()

    @classmethod
    def response_headers(cls, headers):
        res = []
        for header in headers.keys():
            res.append(f"{header}: {headers[header]}\r\n".encode())
        return b"".join(res)

    @classmethod
    def render_html(cls, filename):
        response_line = cls.response_line(status_code=200)
        response_headers = cls.response_headers({"Content-Type": "text/html"})
        with open(filename, "rb") as file:
            response_body = file.read()
            for key in data.get(filename, {}).keys():
                # Loop through each key, replacing with appropriate value in file
                # In a more complex app, this would probably be a function of its own
                response_body = response_body.replace(
                    f"${{{key}}}".encode(), data[filename][key].encode()
                )
        res = b"".join([response_line, response_headers, b"\r\n", response_body])
        return res

    @classmethod
    def handle_GET(cls, request):
        filename = request.uri.strip("/")
        if not len(filename):
            filename = "index.html"
        if path.exists(filename):
            content_type = mimetypes.guess_type(filename)[0] or "text/html"
            if content_type == "text/html":
                return cls.render_html(filename)

            response_line = cls.response_line(status_code=200)
            response_headers = cls.response_headers({"Content-Type": content_type})
            with open(filename, "rb") as file:
                response_body = file.read()
        elif filename in list(cls.api_routes.keys()):
            response = cls.api_routes[filename]()
            response_line = cls.response_line(status_code=response["status_code"])
            response_headers = cls.response_headers(
                {"Content-Type": response["content_type"]}
            )
            response_body = response["body"].encode()
        else:
            response_line = cls.response_line(status_code=404)
            response_headers = cls.response_headers({"Content-Type": "text/plain"})
            response_body = b"404 Not Found"

        return b"".join([response_line, response_headers, b"\r\n", response_body])


class HTTPRequest:
    request_methods = ["GET", "POST", "PUT", "DELETE"]  # By default, CRUD

    def __init__(self, data, request_methods=request_methods, private_files=[]):
        # The first line of an HTTP request has four parts:
        # Request method
        # URI
        # HTTP version
        # Line break
        self.method = None
        self.uri = None
        self.http_version = "1.1"
        self.valid = True  # By default, valid request
        self.request_methods = request_methods
        self.private_files = private_files

        self.parse(data)

    def private_route(self):
        uri = self.uri.strip("/")
        for private_file in self.private_files:
            if uri.startswith(private_file):
                return True
        return False

    def parse(self, data):
        lines = data.split(b"\r\n")
        request_line = lines[0]

        words = request_line.split(b" ")

        self.method = words[0].decode()
        if len(words) > 1:
            self.uri = words[1].decode()
        if len(words) > 2:
            self.http_version = words[2]

        if self.method not in self.request_methods or self.private_route():
            # Not valid request anymore
            self.valid = False


if __name__ == "__main__":
    server = HTTPServer()
    server.start()
