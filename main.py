from os import environ, listdir
from urllib import request, parse
from urllib.request import Request, urlopen
import json, socket

# Load environment variables
env = {}
try:
    with open(".env") as file:
        for line in file.readlines():
            key = ""
            for chr in line:
                if chr == "=":
                    break
                key += chr
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
        {
            "grant_type": "refresh_token",
            "refresh_token": env.get("SPOTIFY_REFRESH_TOKEN"),
        }
    ).encode()

    req = Request("https://accounts.spotify.com/api/token", method="POST", data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Authorization", f"Basic {env.get('SPOTIFY_ENCODED_TOKEN')}")
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
    return song_str


def get_posts():
    """Get the posts I've made, stored in /posts."""
    posts = []
    for file in listdir("./posts"):
        with open(f"./posts/{file}") as f:
            posts.append({"date": file.strip(".md"), "content": f.read()})
    return json.dumps(posts)


# Define socket host and port
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(env.get("PORT"))

# Create socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind((SERVER_HOST, SERVER_PORT))
server_socket.listen()
print(f"Listening on port {SERVER_PORT}")

REQUEST_METHODS = ["GET"]


def prefix(filename, data={}):
    """Return file with prefixed headers, with custom templating for HTML files."""
    try:
        with open(filename, encoding="utf-8") as file:
            content = file.read()
            for key in data.keys():
                content = content.replace(f"${{{key}}}", data.get(key))
            return f"""HTTP/1.0 200 OK\n\n{content}"""
    except FileNotFoundError:
        return "HTTP/1.0 404 NOT FOUND"
    except UnicodeDecodeError:
        with open(filename, "rb") as file:
            # This works locally, but doesn't work when deployed by Render, Railway, etc?
            return file.read()


def parse_headers(headers):
    res = {"general": [], "pairs": {}}

    for header in headers:
        if len(header) == 0 or header in ["\r", "\n"]:
            continue

        is_request = False
        for request_type in REQUEST_METHODS:
            if header.startswith(request_type):
                res["pairs"][request_type] = header.lstrip(f"{request_type}").strip()
                is_request = True

        if is_request:
            continue

        key = ""
        for chr in header:
            if chr == ":":
                break
            key += chr

        if len(key) != len(header):
            res["pairs"][key] = header.lstrip(f"{key}:").strip()
        else:
            res["general"].append(key)

        return res


while True:
    try:
        # Wait for client connections
        client_connection, client_address = server_socket.accept()

        # Get the client request
        req = client_connection.recv(1024).decode()

        if req:
            # Send HTTP response
            headers = parse_headers(req.split("\n"))
            if headers["pairs"].get("GET"):
                route = (
                    headers["pairs"]["GET"]
                    .replace("HTTP/1.0", "")
                    .replace("HTTP/1.1", "")
                    .replace("HTTP/2.0", "")
                    .strip()
                )

                data = {}
                if route == "/":
                    # Here's where we add the custom templating data for the / route!
                    route = "index.html"
                    data = {"song": listening_to(), "posts": get_posts()}

                response = prefix(route.strip("/"), data)
                if type(response) == bytes:
                    client_connection.sendall(response)
                else:
                    client_connection.sendall(
                        response.encode(encoding="ascii", errors="xmlcharrefreplace")
                    )
    except Exception as e:
        print(e)
    finally:
        client_connection.close()

server_socket.close()
