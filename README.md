# JSec

Local security camera tools for the O-KAM CB54W.

Open http://127.0.0.1:8765. The viewer reconnects the `okam-local` Wi-Fi profile on `wlp2s0`, then connects directly to the camera at 192.168.168.1. Ethernet can remain connected for the computer's internet access.

Each new camera session authenticates, reapplies `cueToneVolume=0` to silence the Wi-Fi setup prompt independently of the speaker, mutes the speaker and sets microphone volume to 25, and initializes video plus two-way audio. Prompt suppression was previously confirmed by listening while music played; the firmware only returns command success, not a readable prompt-volume value. These settings are reapplied after reconnects; suppression before the computer connects is not guaranteed.

The prompt-only setting proved unreliable: announcements returned. The viewer now defaults to speaker volume zero on startup and keeps that setting on reconnect. **Enable camera speaker** explicitly restores volume 10/31 for talk-back or music; announcements may return when enabled. **Mute camera speaker** restores silence. The setting is read back from the camera.

Video appears automatically. Click **Listen** for camera audio. Click **Talk** and allow browser microphone permission to speak through the camera; click again to stop. Audio transport is G.711 A-law, 16 kHz mono. Incoming CB54W frame type 12 carries 640 samples every 40 ms. Browser playback and microphone capture require explicit interaction. The camera receives audio, not outgoing video.

With computer recording off, pause live view or close the page to release the camera session after approximately 20 seconds, allowing its existing power-saving behavior. The local server can stay running while the camera sleeps. Opening/resuming the page starts a new session. A sleeping camera may require waking before its hotspot is reachable.

## Motion recordings

The inspected camera settings already have PIR/human detection enabled and lowPower=30 (power-saving mode). It currently reports **no microSD card**. The **Motion recording** panel has independent computer and microSD checkboxes and an Apply button. Both can be selected. Preferences are saved in recording.json and start disabled/unconfigured.

Computer mode keeps the session open even with the browser closed, checks reduced grayscale frames for motion (at least 3% of pixels changing by more than 25 brightness levels, for two consecutive samples), and saves silent H.264 MP4 clips in recordings/. Sampling is approximately 5 fps with up to 2 seconds of buffered frames, a 10-second quiet tail and a 60-second maximum per clip. Download completed clips from the viewer. Changes in lighting or camera position can also trigger clips; this is motion detection, not person recognition. Recording stops starting new clips at 2 GB total storage or below 1 GB free space, without deleting anything. The service and computer must remain running. Interrupted clips retain a .partial.mp4 suffix and are not listed as completed.

MicroSD mode waits for detected storage, disables scheduled continuous recording, then sends the SDK alarm-recording controls (record=1, motion armed, all-day schedule, audible alarm disabled). These settings are reapplied on connection. Unchecking sends record=0. The status distinguishes a missing card from an accepted command; actual onboard clips have not been verified on this camera. Insert a card and click Apply again to retry. Nothing formats cards automatically. The battery camera's existing PIR/power settings are preserved.

## Running

Clone this repository and install Python dependencies with
`python3 -m pip install -r requirements.txt`, then run `python3 viewer.py`
from the checkout. FFmpeg and NetworkManager must be installed separately.
Python 3.13 and newer are unsupported because they removed `audioop`.

The existing local installation is now at
`/home/julian/Documents/Organization/JSec`; the former
`/home/julian/Documents/okam-local` path is a compatibility symlink for the
installed user service. On a new machine, run the viewer directly or configure
a user service with the new checkout as its working directory.

Recordings, logs, local recording preferences, and device configuration snapshots
are local runtime data and are excluded from Git.


Dependencies: system Python 3.10–3.12 (uses audioop), FFmpeg and NetworkManager/nmcli. Pillow is required for motion detection (installed on this computer). `OKAM_CAMERA_PASSWORD` overrides the factory password.

- Start: `systemctl --user start okam-local-viewer`
- Stop: `systemctl --user stop okam-local-viewer`
- Logs: `journalctl --user -u okam-local-viewer` and `ffmpeg.log`
- Tests: `python3 -m unittest discover -s . -p 'test_*.py'`

The service is installed but not enabled at login. Its working directory is this directory. It listens only on 127.0.0.1:8765 and checks HTTP Host and POST Origin. No vendor account or cloud endpoint is used by the viewer. The current implementation expects the camera's DHCP lease to assign this computer 192.168.168.10.

## Network isolation

The camera stays on its own hotspot and has not been given home Wi-Fi credentials. This alone is not a verified firewall guarantee: Linux forwarding is enabled on the computer. `isolate-camera.sh` installs persistent nftables rules blocking forwarding between the camera interface and other networks. It requires administrator access:

```
sudo ./isolate-camera.sh
```

This reserves wlp2s0 for local camera traffic. Firewall installation was not completed by the unprivileged viewer; verify `sudo nft list table inet okam_local` before treating internet isolation as enforced.

Protocol research was informed by the vendor Flutter SDK and https://github.com/jlawrence6809/eversecu-cameras. Vendored talk helpers retain their license in vendor/. The viewer uses its own protocol.py framing implementation. viewer-before-audio.py preserves the previous video-only version.
