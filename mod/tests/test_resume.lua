local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local resume = require('beamngEarth/resume')
local geodesy = require('beamngEarth/geodesy')
local files, writes, fail = {}, 0, nil
function jsonReadFile(path)
  if files[path] == 'broken' then error('incomplete JSON') end
  return files[path]
end
function jsonWriteFile(path, p)
  writes = writes + 1
  if fail == 'partial' then files[path] = 'broken'; error('interrupted write') end
  if fail == 'silent' then return false end
  files[path] = {}
  for k, v in pairs(p) do files[path][k] = v end
end
log = function() end

core_gamestate = {state={state='freeroam'}}
T.check(resume.singleplayerFreeroam(), 'singleplayer freeroam eligible')
for _, mode in ipairs({'multiplayer','scenario','mission','career','menu'}) do
  core_gamestate.state.state=mode
  T.check(not resume.singleplayerFreeroam(), mode..' cannot use singleplayer progress')
end
core_gamestate.state.state='freeroam'
MPCoreNetwork={isMPSession=function() return true end}
T.check(not resume.singleplayerFreeroam(), 'BeamMP excluded even before it changes the game state')
MPCoreNetwork=nil
career_career={isActive=function() return true end}
T.check(not resume.singleplayerFreeroam(), 'career freeroam excluded')
career_career=nil
gameplay_missions_missionManager={getForegroundMissionId=function() return 'active-mission' end}
T.check(not resume.singleplayerFreeroam(), 'foreground mission excluded even with freeroam UI')
gameplay_missions_missionManager=nil
core_gamestate=nil
T.check(not resume.singleplayerFreeroam(), 'unknown mode does not save or restore')

T.check(resume.load() == nil, 'first run without a checkpoint')
local a = geodesy.newAnchor(42.96484, -83.85241)
local p = resume.capture(a, {x=12000,y=4300,z=255}, {x=1,y=0,z=0})
T.check(resume.valid(p), 'capture geographic position and true heading')
local b = geodesy.newAnchor(p.lat, p.lon)
local x, y, z = b:geodeticToEnu(p.lat,p.lon,p.height)
T.near(x,0,1e-6,'return to saved longitude')
T.near(y,0,1e-6,'return to saved latitude')
local dx,dy = resume.direction(b,x,y,p.heading)
local expectedX,expectedY = a:transformTo(b):rotate(1,0,0)
local length = math.sqrt(expectedX^2+expectedY^2)
T.near(dx,expectedX/length,1e-5,'heading east component survives rebase')
T.near(dy,expectedY/length,1e-5,'heading north component survives rebase')
for _, h in ipairs({0,90,180,270,359.99}) do
  local hx,hy=resume.direction(b,0,0,h)
  local captured=resume.capture(b,{x=0,y=0,z=z},{x=hx,y=hy,z=0})
  T.near(captured.heading,h,1e-8,'heading round trip '..h)
end
T.check(not resume.capture(a,{x=0/0,y=0,z=0},{x=1,y=0}), 'NaN pose rejected')
T.check(not resume.capture(a,{x=0,y=0,z=0},{x=0,y=0}), 'undefined heading rejected')
T.check(not resume.tick(9,10,p), 'no write before interval')
T.check(resume.tick(1,10,p) and writes==1, 'save at interval')
T.check(resume.load().sequence==1, 'reload last completed checkpoint')
p.lon=p.lon+0.01
T.check(resume.tick(0,10,p,true), 'final save before interval')
local latest=resume.load()
T.check(latest.sequence==2 and latest.lon==p.lon, 'newest checkpoint selected')
fail='partial'
T.check(not resume.save(p), 'partial write reported')
T.check(resume.load().sequence==2, 'partial write keeps last completed checkpoint')
fail='silent'
T.check(not resume.save(p) and resume.load().sequence==2, 'failed write never replaces good save')
fail=nil
T.check(resume.save(p), 'saving recovers after write failure')
files[resume.FILES[1]]={version=1,sequence=100,lat=999,lon=0,height=0,heading=0}
T.check(resume.load().sequence==2, 'invalid newer coordinates fall back to valid backup')
local before=writes
resume.tick(9,10,p)
resume.tick(1,10,nil)
T.check(not resume.tick(1,10,p) and writes==before, 'loading resets timer and does not save')
T.check(resume.tick(0,10,p,true), 'normal exit can save immediately')
T.done('test_resume')
