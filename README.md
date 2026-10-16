# Questie-335 for mod-individual-progression

Questie for WoW 3.3.5a (12340) on an AzerothCore server that runs
[mod-individual-progression](https://github.com/Grimfeather/mod-individual-progression).

This is a fork of [Aldori15/Questie](https://github.com/Aldori15/Questie), the actively maintained
Questie-335 that matches stock AzerothCore 1:1. All of Questie's features and AzerothCore data come from
there; credit for the addon goes to Aldori15 and the original Questie team.

## What this fork adds

mod-individual-progression changes a lot of the game: it restores vanilla quest levels, objectives,
reputation rewards, quest givers and spawns, and adds its own quests and NPCs. Aldori15's AzerothCore
corrections leave the module out on purpose, so on such a server stock Questie shows the wrong levels,
givers and spawns for hundreds of quests.

This fork adds one layer, `Database/IndividualProgression/`, that loads after Aldori15's
`Database/AzerothCore/` corrections and holds only what the live server does differently:

- About 2,750 quest corrections: levels, objectives (Soothing Turtle Bisque also needs Soothing Spices),
  reputation, givers and finishers.
- The module's own quests, which Questie does not know: Simply Bang a Gong!, Chaos and Destruction, the
  Colossus quests, Complete the War Effort and more.
- About 4,900 NPC, 350 object and 4,500 item corrections, including the module's NPCs (Horde Warbringer,
  ...) and other custom content on the server.

Aldori15's files are left untouched, so his updates can be merged into this fork without conflicts.

## Installation

- [Download](https://github.com/Tntdruid/QuestieAzeroth/archive/refs/heads/335.zip) the archive.
- Extract it into the `Interface/AddOns/` directory. The folder name must be `Questie-335`.
- Restart WoW. The first login takes a little longer while Questie builds its database.

Without mod-individual-progression on your server, use [Aldori15/Questie](https://github.com/Aldori15/Questie) instead.

## Updating the server layer

The layer is generated from a HeidiSQL export of the live `acore_world` database by
`tools/generate_ip_overlay.py`, which runs Aldori15's own AzerothCore generators and validators. After
updating the server or a module, export the database again and run (about an hour):

```
python tools/generate_ip_overlay.py --acore-source D:/azerothcore-wotlk --live-dump D:/azerothcore-live-dump/acore_world.sql --work-dir D:/questie-ip-work --map-difficulty-dbc D:/azerothcore-wotlk/env/dist/bin/dbc/MapDifficulty.dbc
lua tools/tests/test_ip_overlay_loading.lua
```

The script adds the export's date to the TOC version (`10.0.1-335-ip20261016`), so Questie rebuilds its
database after an update. Quests 90000-99999 (the server owner's test quests) are left out. The script's
docstring describes how each part is found.

## Optional AzerothCore Server Bridge Module

Install [mod-questie-bridge](https://github.com/Aldori15/mod-questie-bridge) on your AzerothCore
server to let Questie follow live server state:

- Holidays, fishing tournaments, Scourge Invasion, and Isle of Quel'Danas unlocks.
- Selected daily/weekly quest pools, ICC weekly quests, and Wintergrasp control.
- Weekly/monthly quest resets and live XP, reputation, and money rates.
- Moving questgiver markers in your current zone, including Orgrim's Hammer and the Skybreaker.
- Phase-dependent locations in supported story areas, including Icecrown, Storm Peaks, and the death knight start.
- World Progress in related Journey quest details and tooltips.

See the [module setup instructions](https://github.com/Aldori15/mod-questie-bridge#installation).
Install matching addon and module builds, then log in or `/reload`. Run `/qserver` to check the connection;
`/qserver xp`, `/qserver rep [faction ID]`, and `/qserver money` show reward rates.
The module README lists the other diagnostic commands.

Server rate changes appear within a few seconds; rehover or reopen the reward display to refresh it.
Rewards are estimates: server rounding, caps, or custom rules can affect the final amount awarded.
Moving markers work in your current zone; other zones keep their static locations and patrol lines.
Phase filtering applies within your current subarea. Quest prerequisites and your visibility settings still apply.

Enable **Available Scourge Invasion Quests** or **Available Sun's Reach Quests** to show those quest sets.
The bridge is optional. Missing, disabled, or expired server information restores Questie's usual behavior.

## Questie Information
- [Frequently Asked Questions](https://github.com/Questie/Questie/wiki/FAQ)
- Come chat with us on [our Discord server](https://discord.gg/s33MAYKeZd).
- Report problems with this fork's server layer in its [issue tracker](https://github.com/Tntdruid/QuestieAzeroth/issues). Bugs in Questie itself belong in [Aldori15's issue tracker](https://github.com/Aldori15/Questie/issues) (requires a Github account).
- If you get an error message from the WoW client, please include the **complete** text or a screenshot of it in your report.
    - You need to enter `/console scriptErrors 1` once in the ingame chat for Lua error messages to be shown. You can later disable them again with `/console scriptErrors 0`.

Trust us it's (Good)!

# Features

### Show quests on map
- Show notes for quest start points, turn in points, and objectives.

![Questie Quest Givers](https://i.imgur.com/4abi5yu.png)
![Questie Complete](https://i.imgur.com/DgvBHyh.png)
![Questie Tooltip](https://i.imgur.com/uPykHKC.png)

### Quest Tracker
- Improved quest tracker:
    - Automatically tracks quests on accepting
    - Can show all 20 quests from the log (instead of default 5)
    - Left click quest to open quest log (configurable)
    - Right-click for more options, e.g.:
        - Focus quest (makes other quest icons translucent)
        - Point arrow towards objective (requires TomTom addon)

![QuestieTracker](https://user-images.githubusercontent.com/8838573/67285596-24dbab00-f4d8-11e9-9ae1-7dd6206b5e48.png)

### Quest Communication
- You can see party members quest progress on the tooltip.
- You can announce objective progress, objective complete, quest complete, quest accept, quest abandon to chat.

<img width="483" height="281" alt="image" src="https://github.com/user-attachments/assets/bed0522f-31e8-4ca1-a9fe-0927a12599df" />

### Tooltips
- Show tooltips on map notes and quest NPCs/objects.
- Holding Shift while hovering over a map icon displays more information, like quest XP.
- Show quest names on the tooltip of items that begin a quest.

<img width="707" height="160" alt="image" src="https://github.com/user-attachments/assets/d85698ba-7fdb-428c-a876-02cb8cc698f9" />

<img width="447" height="365" alt="image" src="https://github.com/user-attachments/assets/df379e3b-682c-404d-a966-c5b88d5856bf" />

#### Waypoints

- Waypoint lines for quest givers showing their pathing.
- With the TomTom addon, you can shift+left click an icon on the map to place a waypoint and navigate.

<img width="853" height="495" alt="image" src="https://github.com/user-attachments/assets/380aa249-927b-4132-aa54-3b267bbd0a2f" />

<img width="202" height="166" alt="image" src="https://github.com/user-attachments/assets/a44a1b5e-9bd0-49ae-9e27-b932050bd9f3" />

### Journey Log
- Questie records the steps of your journey in the "My Journey" window. (left-click on minimap button and select the "My Journey" tab or type `/questie journey`)

![Journey](https://user-images.githubusercontent.com/8838573/67285651-3cb32f00-f4d8-11e9-95d8-e8ceb2a8d871.png)

### Quests by Zone
- Questie lists all the quests of a zone divided between completed and available quest. Gotta complete 'em all. (left-click on minimap button (or type `/questie journey`) and select the "Quests by Zone" tab

![QuestsByZone](https://user-images.githubusercontent.com/8838573/67285665-450b6a00-f4d8-11e9-9283-325d26c7c70d.png)

### Quests by Faction
- Similarly to Quests by Zone, Questie lists all the quests of a faction divided between completed and available quest. Gotta complete 'em all. (left-click on minimap button (or type `/questie journey`) and select the "Quests by Faction" tab

### Search
- Questie's database can be searched. (left-click on minimap button (or type `/questie journey`) and select the "Advanced Search" tab

![Search](https://user-images.githubusercontent.com/8838573/67285691-4f2d6880-f4d8-11e9-8656-b3e37dce2f05.png)

### Configuration
- Extensive configuration options. (right-click on minimap button to open or type `/questie`)
