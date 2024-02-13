# This file is part of mkchromecast.
"""
These functions are used to get up the streaming server using node.

To call them:
    from mkchromecast.node import *
    name()
"""

# This file is audio-only for node.  Video via node is (currently) handled
# completely within video.py.

import configparser as ConfigParser
import multiprocessing
import os
import pickle
import psutil
import time
import re
import sys
import signal
import subprocess

import mkchromecast
from mkchromecast.audio_devices import inputint, outputint
from mkchromecast import colors
from mkchromecast import constants
from mkchromecast import utils
from mkchromecast.cast import Casting
from mkchromecast.config import config_manager
from mkchromecast.constants import OpMode
from mkchromecast.preferences import ConfigSectionMap


def streaming(mkcc: mkchromecast.Mkchromecast):
    """
    Configuration files
    """
    config = ConfigParser.RawConfigParser()
    # Class from mkchromecast.config
    configurations = config_manager()
    configf = configurations.configf

    bitrate: int
    if os.path.exists(configf) and mkcc.operation == OpMode.TRAY:
        configurations.chk_config()
        print(colors.warning("Configuration file exists"))
        print(colors.warning("Using defaults set there"))
        config.read(configf)
        backend = ConfigSectionMap("settings")["backend"]

        # TODO(xsdg): dedup this parsing code between audio.py and node.py.
        stored_bitrate = ConfigSectionMap("settings")["bitrate"]
        if stored_bitrate == "None":
            print(colors.warning("Setting bitrate to default of "
                                 f"{constants.DEFAULT_BITRATE}"))
            bitrate = constants.DEFAULT_BITRATE
        else:
            # Bitrate may be stored with or without "k" suffix.
            bitrate_match = re.match(r"^(\d+)k?$", stored_bitrate)
            if not bitrate_match:
                raise Exception(
                    f"Failed to parse bitrate {repr(stored_bitrate)} as an "
                    "int. Expected something like '192' or '192k'")
            bitrate = int(bitrate_match[1])

        samplerate = ConfigSectionMap("settings")["samplerate"]
        notifications = ConfigSectionMap("settings")["notifications"]
    else:
        backend = mkcc.backend
        codec = mkcc.codec
        bitrate = mkcc.bitrate
        samplerate = str(mkcc.samplerate)
        notifications = mkcc.notifications

    print(colors.options("Selected backend:") + " " + backend)

    if mkcc.debug is True:
        print(
            ":::node::: variables %s, %s, %s, %s, %s"
            % (backend, codec, bitrate, samplerate, notifications)
        )

    if mkcc.youtube_url is None:
        if backend == "node":
            bitrate = utils.clamp_bitrate(codec, bitrate)
            print(colors.options("Using bitrate: ") + f"{bitrate}k.")

            if codec in constants.QUANTIZED_SAMPLE_RATE_CODECS:
                samplerate = str(utils.quantize_sample_rate(codec, samplerate))

            print(colors.options("Using sample rate:") + f" {samplerate}Hz.")

    """
    Node section
    """
    paths = ["/usr/local/bin/node", "./bin/node", "./nodejs/bin/node"]

    for path in paths:
        if os.path.exists(path) is True:
            webcast = [
                path,
                "./nodejs/node_modules/webcast-osx-audio/bin/webcast.js",
                "-b",
                bitrate,
                "-s",
                samplerate,
                "-p",
                "5000",
                "-u",
                "stream",
            ]
            break
    else:
        webcast = None
        print(colors.warning("Node is not installed..."))
        print(
            colors.warning("Use your package manager or their official " "installer...")
        )
        pass

    if webcast is not None:
        p = subprocess.Popen(webcast)

        if mkcc.debug is True:
            print(":::node::: node command: %s." % webcast)

        f = open("/tmp/mkchromecast.pid", "rb")
        pidnumber = int(pickle.load(f))
        print(colors.options("PID of main process:") + " " + str(pidnumber))

        localpid = os.getpid()
        print(colors.options("PID of streaming process: ") + str(localpid))

        while p.poll() is None:
            try:
                time.sleep(0.5)
                # With this I ensure that if the main app fails, everything
                # will get back to normal
                if psutil.pid_exists(pidnumber) is False:
                    inputint()
                    outputint()
                    parent = psutil.Process(localpid)
                    # or parent.children() for recursive=False
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
            except KeyboardInterrupt:
                print("Ctrl-c was requested")
                sys.exit(0)
            except IOError:
                print("I/O Error")
                sys.exit(0)
            except OSError:
                print("OSError")
                sys.exit(0)
        else:
            print(colors.warning("Reconnecting node streaming..."))
            if mkcc.platform == "Darwin" and notifications == "enabled":
                if os.path.exists("images/google.icns") is True:
                    noticon = "images/google.icns"
                else:
                    noticon = "google.icns"
            if mkcc.debug is True:
                print(
                    ":::node::: platform, tray, notifications: %s, %s, %s."
                    % (mkcc.platform, mkcc.tray, notifications)
                )

            if mkcc.platform == "Darwin" and mkcc.operation == OpMode.TRAY and notifications == "enabled":
                reconnecting = [
                    "./notifier/terminal-notifier.app/Contents/MacOS/terminal-notifier",
                    "-group",
                    "cast",
                    "-contentImage",
                    noticon,
                    "-title",
                    "mkchromecast",
                    "-subtitle",
                    "node server failed",
                    "-message",
                    "Reconnecting...",
                ]
                subprocess.Popen(reconnecting)

                if mkcc.debug is True:
                    print(
                        ":::node::: reconnecting notifier command: %s." % reconnecting
                    )

            # This could potentially cause forkbomb-like behavior where each new
            # child process would create a new child process, ad infinitum.
            raise Exception("Internal error: Never worked; needs to be fixed.")

            relaunch(stream_audio, recasting, kill)
        return


class multi_proc(object):
    def __init__(self):
        self._mkcc = mkchromecast.Mkchromecast()
        self.proc = multiprocessing.Process(target=streaming, args=(self._mkcc,))
        self.proc.daemon = False

    def start(self):
        self.proc.start()


def kill():
    pid = os.getpid()
    os.kill(pid, signal.SIGTERM)
    return


def relaunch(func1, func2, func3):
    func1()
    func2()
    func3()
    return


def recasting():
    mkcc = mkchromecast.Mkchromecast()
    start = Casting(mkcc)
    start.initialize_cast()
    start.get_devices()
    start.play_cast()
    return


def stream_audio():
    st = multi_proc()
    st.start()
