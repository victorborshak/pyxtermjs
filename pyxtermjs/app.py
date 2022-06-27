#!/usr/bin/env python3
import argparse
from flask import Flask, render_template
from flask_socketio import SocketIO, Namespace, emit
import pty
import os
import subprocess
import select
import termios
import struct
import fcntl
import shlex
import logging
import sys

logging.getLogger("werkzeug").setLevel(logging.ERROR)

__version__ = "0.5.0.0"

app = Flask(__name__, template_folder=".", static_folder=".", static_url_path="")
app.terminals = []
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app)

class MyTerminal(Namespace):
    def on_connect(self):
        logging.info("== NEW CONNECTION TO NAMESPACE == " + self.namespace)
        (child_pid, fd) = pty.fork()
        if child_pid == 0:
            subprocess.run(app.config["cmd"])
        else:
            # memorize the fd of the pty
            self.fd = fd
            self.set_winsize(fd, 50, 50)
            # start listening to websocket stream
            socketio.start_background_task(self.read_and_forward_pty)

    def on_disconnect(self):
        pass

    def on_resize(self, data):
        logging.debug(f"Resizing window to {data['rows']}x{data['cols']}")
        self.set_winsize(self.fd, data["rows"], data["cols"])
        pass

    def on_pty_input(self, data):
        if self.fd:
            logging.debug("received input from browser: %s" % data["input"])
            # write data to fd
            os.write(self.fd, data["input"].encode())

    def read_and_forward_pty(self):
        max_read_bytes = 1024 * 20

        # wait for data in fd and forward it to websocket
        while True:
            socketio.sleep(0.01)
            timeout_sec = 0
            (data_ready, _, _) = select.select([self.fd], [], [], timeout_sec)
            if data_ready:
                output = os.read(self.fd, max_read_bytes).decode()
                socketio.emit("pty-output", {"output": output}, namespace = self.namespace)

    def set_winsize(self, fd, row, col, xpix=0, ypix=0):
        logging.debug("setting window size with termios")
        winsize = struct.pack("HHHH", row, col, xpix, ypix)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

@app.route("/")
def index():
    return render_template("index.html")

@app.route('/terminal', methods = ['POST'])
def terminal():
    termindex = len(app.terminals)+1
    newterm = {
        "name": termindex
    }
    app.terminals.append(newterm)
    logging.info("== CREATING NEW NAMESPACE == ")
    socketio.on_namespace(MyTerminal('/pty/{index}'.format(index=termindex)))
    return newterm

def main():
    parser = argparse.ArgumentParser(
        description=(
            "A fully functional terminal in your browser. "
            "https://github.com/cs01/pyxterm.js"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-p", "--port", default=5000, help="port to run server on")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="host to run server on (use 0.0.0.0 to allow access from other hosts)",
    )
    parser.add_argument("--debug", action="store_true", help="debug the server")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument(
        "--command", default="bash", help="Command to run in the terminal"
    )
    parser.add_argument(
        "--cmd-args",
        default="",
        help="arguments to pass to command (i.e. --cmd-args='arg1 arg2 --flag')",
    )
    args = parser.parse_args()
    if args.version:
        print(__version__)
        exit(0)
    app.config["cmd"] = [args.command] + shlex.split(args.cmd_args)
    green = "\033[92m"
    end = "\033[0m"
    log_format = green + "pyxtermjs > " + end + "%(levelname)s (%(funcName)s:%(lineno)s) %(message)s"
    logging.basicConfig(
        format=log_format,
        stream=sys.stdout,
        level=logging.DEBUG if args.debug else logging.INFO,
    )
    logging.info(f"serving on http://127.0.0.1:{args.port}")
    socketio.run(app, debug=args.debug, port=args.port, host=args.host)

if __name__ == "__main__":
    main()
