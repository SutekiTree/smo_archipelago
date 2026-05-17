# Changing servers, slots, and bridge PCs

There are two categories of "I want to change something" — they have very
different costs. Knowing which is which saves time.

## TL;DR

| What you want to change | Rebuild required? | How |
|---|---|---|
| AP server address (host:port) | **No.** | Type `/connect <host>:<port> <slot>` in SMOClient, or pass `--connect <host>:<port>` on the CLI, or double-click a fresh `.smoap` from a different AP gen. |
| AP slot name | **No.** | Use the same `/connect` trick or `--name <slot>`, or double-click the new `.smoap`. |
| AP password | **No.** | `/connect <host>:<port> <slot> <password>`, or `--password <pwd>`. |
| Switch listen port (PC side) | **No.** | Edit `host.yaml` or pass `--switch-port`. |
| Bridge PC's LAN IP | **Yes.** Re-run the setup wizard. | Type `/setup` in SMOClient or double-click any `.smoap` after deleting `%APPDATA%/SMOArchipelago/`. |
| Switching to a different bridge PC | **Yes.** Set up on the new PC. | Run the wizard on the new PC. |

## Per-session: server, slot, password

These all live in SMOClient's runtime configuration. The Switch mod doesn't
know or care about them — it only knows about the bridge PC's IP. So
changing any of these is a click-and-type operation, never a rebuild.

### From the SMOClient GUI

The Kivy command bar at the bottom of the SMOClient window accepts the
standard Archipelago commands:

```
/disconnect
/connect archipelago.gg:38281 Mario
```

You can also paste `archipelago.gg:38281` directly into the Connect bar at
the top of the window and click **Connect**.

### From the command line

Pass overrides when launching SMOClient:

```pwsh
python vendor\Archipelago\Launcher.py "SMO Client" `
    --connect archipelago.gg:38281 --name Mario --password hunter2
```

### By double-clicking a `.smoap` file

Every multiworld you join gives you a `<player>.smoap` file. Double-clicking
it routes through Archipelago Launcher → SMOClient with the slot name
pre-filled. If the generator's host also filled the server address (an
optional field in the `.smoap` JSON), the Connect bar is pre-populated too;
otherwise type it in and click Connect.

### Per-session DeathLink toggle

The default is set in `host.yaml` (`smo_options.deathlink_default`). To
override for a single launch, pass `--deathlink` on the CLI. The Switch
mod respects whatever the bridge tells it during the HELLO handshake, so
flipping the flag mid-session requires a SMOClient restart but no rebuild.

## Per-machine: bridge PC's IP

This is the rebuild-required case. The bridge IP is baked into the Switch
module (`subsdk9`) at compile time, because retail Switch firmware doesn't
let our module read configuration from the SD card at runtime.

You need to re-run the wizard when:

- You move to a new LAN with a different IP range
- Your router gave you a different DHCP lease and the old IP no longer works
- You switch to using a different PC as the bridge

### Quickest path

1. Open SMOClient (any way you usually do — clicking "SMO Client" in the
   Archipelago Launcher works, or just double-click any old `.smoap`).
2. Type `/setup` in the command bar.
3. The wizard opens in a fresh window. Walk forward — you can usually
   skip-by-rechecking the prereqs and extraction pages (their outputs are
   cached at `%APPDATA%/SMOArchipelago/data/`), edit the Bridge IP page
   with the new value, let it rebuild, and re-deploy.
4. Restart your Switch / Ryujinx so it picks up the new module.

### What the wizard does behind the scenes

`cmake` reconfigures with `-DBRIDGE_HOST=<new-ip>`, recompiles, and
re-deploys the resulting `subsdk9` to the same destination you picked
originally (SD card or Ryujinx). Build takes about a minute. The Switch
mod reconnects to the new IP on next boot.

## Per-machine: deploy target (SD ↔ Ryujinx)

If you developed against Ryujinx and now want to play on a real Switch (or
vice versa), re-run setup and pick the other deploy target. **No rebuild
needed** — the build artifacts (`subsdk9`, `main.npdm`, `ap_config.json`)
are the same bytes for both targets. The wizard remembers your last choice
in `%APPDATA%/SMOArchipelago/setup_state.json`, so subsequent re-runs
default to that target.

## What never needs a rebuild

Nothing else does. Items, locations, regions, options, the apworld's
internal logic — those all live in the apworld zip, which is loaded fresh
every time SMOClient or AP-server starts. Update the apworld by replacing
the file in `custom_worlds/` and restarting.

A Switch-mod **wire-protocol** change (rare; new message types added
between SMO Archipelago releases) does require both an updated SMOClient
AND a re-deployed Switch module. The wizard's `/setup` flow handles both
in one shot.
