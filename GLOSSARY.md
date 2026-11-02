# MCWorldControl

MCWorldControl helps friends who play occasionally run a shared Minecraft world without keeping its server running around the clock.

## Language

**Server**:
A hosted Minecraft world that a group can start when they want to play and stop between sessions.
_Avoid_: EC2 instance, machine

**Idle shutdown**:
Automatic stopping of a server after it has had no players for a period of time.
_Avoid_: World deletion

**Owner**:
The person who owns a server and can delete it or choose its admins.
_Avoid_: Admin

**Admin**:
A person granted shared control of a server, including starting, stopping, renaming, and managing player access.
An admin cannot delete the server or manage its admins.
_Avoid_: Owner, player

**Player access**:
The rules determining who may join a server in Minecraft: anyone, or only players on its allowlist.
Player access does not grant control of the server.
_Avoid_: Admin access
