# Local Tapo P100 Control

This controls the Tapo P100 at `192.168.1.107` over the LAN using
`python-kasa`. It does not send on/off commands through the Tapo cloud, but the
plug still uses your TP-Link/Tapo credentials for local authentication.

## One-time Tapo setup

In the Tapo app, enable third-party local access:

`Me > Third-Party Services > Third-Party Compatibility`

Keep the router DHCP reservation pinned to:

`98-BA-5F-C6-F0-A0 -> 192.168.1.107`

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Edit `.env` and enter your TP-Link/Tapo account email and password.

## Use

```powershell
.\.venv\Scripts\python.exe .\tapo_p100.py state
.\.venv\Scripts\python.exe .\tapo_p100.py on
.\.venv\Scripts\python.exe .\tapo_p100.py off
.\.venv\Scripts\python.exe .\tapo_p100.py toggle
```

For automation:

```powershell
.\.venv\Scripts\python.exe .\tapo_p100.py state --json
```

## If connection fails

Try the discovery path:

```powershell
.\.venv\Scripts\python.exe .\tapo_p100.py state --connection auto
```

If you get an authentication or handshake error:

- confirm `.env` uses the exact Tapo account email, preferably lowercase
- disable and re-enable Third-Party Compatibility in the Tapo app
- let the plug reach the internet once after changing account/app settings, then
  retry local control
- if it still fails after a firmware update, factory reset the plug, add it back
  to Tapo, enable Third-Party Compatibility, and retry

You can also use the installed `kasa` CLI directly:

```powershell
.\.venv\Scripts\kasa.exe --host 192.168.1.107 --type smart --username "you@example.com" --password "password" state
.\.venv\Scripts\kasa.exe --host 192.168.1.107 --type smart --username "you@example.com" --password "password" on
```
