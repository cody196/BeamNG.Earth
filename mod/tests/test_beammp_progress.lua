-- Server persistence and reconnect lifecycle with BeamMP events and an interrupted disk write.
-- Runs under LuaJIT and the server's Lua 5.3.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local function copy(t)
  if type(t) ~= 'table' then return t end
  local out = {}; for k,v in pairs(t) do out[k]=copy(v) end; return out
end
local blobs, serial, files, fail = {}, 0, {}, false
Util = {
  JsonEncode=function(value) serial=serial+1; local s='json:'..serial; blobs[s]=copy(value); return s end,
  JsonDecode=function(text) assert(blobs[text], 'invalid JSON'); return copy(blobs[text]) end,
}
local realOpen = io.open
io.open = function(path, mode)
  if mode == 'r' then
    if not files[path] then return nil end
    return {read=function() return files[path] end, close=function() return true end}
  end
  return {write=function(_, text) files[path]=fail and 'partial JSON' or text; return not fail end,
    close=function() return true end}
end
local events, messages, accounts, guests, names = {}, {}, {}, {}, {}
MP = {
  RegisterEvent=function(name, callback) events[name]=callback end,
  CreateEventTimer=function() end,
  GetPlayerIdentifiers=function(pid) return {beammp=accounts[pid], ip='127.0.0.1'} end,
  IsPlayerGuest=function(pid) return guests[pid]==true end,
  GetPlayerName=function(pid) return names[pid] or 'driver' end,
  TriggerClientEvent=function(pid, name, data) messages[#messages+1]={pid=pid,name=name,data=Util.JsonDecode(data)} end,
}
local path=dir..'/../../beammp/Server/BeamNGEarth/main.lua'
local G=dofile(path)
local function event(name, ... ) return _G[events[name]](...) end
local function pose(pid, progress, extra)
  local d={v=2,aLat=40,aLon=-80,lat=40,lon=-80,resume=1,progress=progress}
  for k,v in pairs(extra or {}) do d[k]=v end
  event('bngePose',pid,Util.JsonEncode(d))
end
local function goTo(pid)
  for i=#messages,1,-1 do local m=messages[i]; if m.pid==pid and m.name=='bngeGoTo' then return m.data end end
end
local function location(lat, heading) return {lat=lat,lon=-84.9,height=230,heading=heading or 90} end

T.check(events.onShutdown and events.onPlayerDisconnect, 'flush handlers registered')
accounts[1]='101'
pose(1,location(42))
T.check(G.checkpoints['101'].lat==42 and not goTo(1), 'first-time driver checkpoint uses authenticated identity')
for _=1,4 do event('BNGE_tick') end
T.check(G.saveSequence==0, 'no disk write before interval')
event('BNGE_tick')
T.check(G.saveSequence==1, 'server timer saves at ten seconds')
pose(1,location(42.01,135))
event('onPlayerDisconnect',1)
T.check(not G.players[1] and G.saveSequence==2, 'disconnect flushes last received stable pose')

-- Restart the server, rename the player, and allocate a different temporary player ID.
G=dofile(path)
T.check(G.checkpoints['101'].lat==42.01,'checkpoint survives server restart')
accounts[7],names[7]='101','renamed driver'
pose(7,location(10),{joined=true})
local target=goTo(7)
T.check(target and target.resume and target.lat==42.01 and target.heading==135, 'reconnect restores location and heading by account')
T.check(G.checkpoints['101'].lat==42.01,'initial join pose cannot overwrite saved position')
pose(7,location(11),{resumeAck='wrong-token'})
T.check(G.checkpoints['101'].lat==42.01,'unacknowledged loading pose ignored')
local messagesBefore=#messages
for _=1,5 do event('BNGE_tick') end
T.check(#messages>messagesBefore and goTo(7).token==target.token,'uncompleted restore is resent with the same token')
pose(7,location(42.02,180),{resumeAck=target.token})
T.check(G.checkpoints['101'].lat==42.02 and not G.players[7].restorePlace, 'successful restore unlocks subsequent saves')
pose(7,nil)
T.check(G.checkpoints['101'].lat==42.02,'free camera cannot replace last driving pose')

-- A different account can reuse the ID/name, without inheriting the previous player's save.
event('onPlayerDisconnect',7)
accounts[7]='202'
messages={}
pose(7,location(43),{account='101',beammp='101'})
T.check(not goTo(7) and G.checkpoints['202'].lat==43 and G.checkpoints['101'].lat==42.02,
  'reused player ID, same name, and spoofed packet identity cannot select another account')
accounts[8],guests[8]='101',true
pose(8,location(5),{joined=true})
T.check(not (goTo(8) and goTo(8).resume) and G.checkpoints['101'].lat==42.02,'guests do not load or overwrite account saves')
pose(9,location(5))
T.check(not G.players[9].account,'missing stable identity is not saved by name or IP')
local previous=G.checkpoints['202'].lat
pose(7,location(0/0))
T.check(G.checkpoints['202'].lat==previous,'NaN progress ignored')
pose(10,nil,{lat=0/0})
T.check(not G.players[10],'NaN broadcast pose rejected')

event('onShutdown')
local goodSequence=G.saveSequence
pose(7,location(44))
fail=true
event('onShutdown')
T.check(G.saveSequence==goodSequence and G.progressDirty,'failed save retains dirty state for retry')
G=dofile(path)
T.check(G.saveSequence==goodSequence and G.checkpoints['202'].lat==43,'partial write recovers previous complete file')
fail=false
event('onPlayerJoining',7)
pose(7,nil)
target=goTo(7)
pose(7,location(44),{resumeAck=target.token})
event('onShutdown')
G=dofile(path)
T.check(G.checkpoints['202'].lat==44,'saving recovers after disk failure')
messages={}
pose(7,location(44.01))
T.check(not goTo(7) and G.checkpoints['202'].lat==44.01,
  'plugin reload leaves connected drivers in place and continues saving without a restore handshake')
G.SAVE_POSITIONS=false
accounts[11]='202'; messages={}
pose(11,location(50))
T.check(not goTo(11) and G.checkpoints['202'].lat==44.01,'server setting disables both save and restore')
io.open=realOpen
T.done('test_beammp_progress')
