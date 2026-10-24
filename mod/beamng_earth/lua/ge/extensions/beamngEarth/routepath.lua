-- Match a local, directed road path to the server's route. Never choose a disconnected
-- road just because its XY crosses a sampled GPS point (bridges and exit ramps).
local M = {}
M.CORRIDOR_M = 25

local function distance(a, b)
  return math.sqrt((a.x-b.x)^2 + (a.y-b.y)^2)
end

-- Both directions are indexed: the stock GE map stores each edge on only one endpoint.
function M.graph(nodes)
  local adj = {}
  for id in pairs(nodes) do adj[id] = {} end
  for a, n in pairs(nodes) do
    for b, edge in pairs(n.links or {}) do
      if nodes[b] then
        if not edge.oneWay or edge.inNode == nil or edge.inNode == a then adj[a][b] = edge end
        if not edge.oneWay or edge.inNode == nil or edge.inNode == b then adj[b][a] = edge end
      end
    end
  end
  return adj
end

local function push(heap, id, cost)
  local i = #heap+1
  while i > 1 do
    local p = math.floor(i/2)
    if heap[p][2] <= cost then break end
    heap[i], i = heap[p], p
  end
  heap[i] = {id,cost}
end

local function pop(heap)
  local top, last = heap[1], table.remove(heap)
  if #heap > 0 then
    local i = 1
    while i*2 <= #heap do
      local j = i*2
      if j < #heap and heap[j+1][2] < heap[j][2] then j = j+1 end
      if last[2] <= heap[j][2] then break end
      heap[i], i = heap[j], j
    end
    heap[i] = last
  end
  return top[1], top[2]
end

-- e is the ENU route {x,y,cum}; a -> b is the forward edge underneath the car.
-- Costs penalize lateral deviations and backwards travel, while the endpoint reward is
-- progress on the planned route. A ramp departing that route cannot become a shortcut
-- to a point on the crossing bridge. A route which actually uses the ramp still matches it.
function M.plan(nodes, adj, e, here, ahead, a, b, pos)
  local diag = {reason='no_forward_edge', start=a, next=b, visited=0, corridor=0, direction=0, horizon=0}
  if not (a and b and adj[a] and adj[a][b]) then return nil, diag end
  local first, last = 1, #e.x-1
  while first < last and e.cum[first+1] < here-100 do first=first+1 end
  while last > first and e.cum[last] > here+ahead do last=last-1 end
  local function project(p)
    local best, at = math.huge, nil
    for i=first,last do
      local dx,dy=e.x[i+1]-e.x[i],e.y[i+1]-e.y[i]
      local len2=dx*dx+dy*dy
      local t=len2>0 and math.max(0,math.min(1,((p.x-e.x[i])*dx+(p.y-e.y[i])*dy)/len2)) or 0
      local d=(p.x-e.x[i]-t*dx)^2+(p.y-e.y[i]-t*dy)^2
      if d < best then best,at=d,e.cum[i]+t*(e.cum[i+1]-e.cum[i]) end
    end
    return {s=at,off=math.sqrt(best)}
  end
  local projections = {}
  local function at(id)
    if not projections[id] then projections[id]=project(nodes[id].pos) end
    return projections[id]
  end
  local start = at(b)
  diag.startOff = start.off
  if start.off > M.CORRIDOR_M then diag.reason='start_outside_route'; return nil, diag end
  if start.s > here+distance(pos,nodes[b].pos)+40 then diag.reason='start_skips_route'; return nil, diag end
  -- OSM routing and the rendered road source can have a small persistent lateral offset.
  -- Penalize departures beyond that band, not every metre driven on the correct carriageway.
  local freeError = math.max(8, start.off+4)
  local heap, costs, prev = {}, {[b]=0}, {}
  push(heap,b,0)
  local best, bestScore = b, start.s
  while #heap>0 do
    local id,cost=pop(heap)
    if cost==costs[id] then
      diag.visited=diag.visited+1
      local p, from=nodes[id].pos,at(id)
      local score=from.s-cost
      if score>bestScore then best,bestScore=id,score end
      for other in pairs(adj[id]) do
        if other~=a then
          local q,to=nodes[other].pos,at(other)
          local len=distance(p,q)
          local mid=project({x=(p.x+q.x)/2,y=(p.y+q.y)/2})
          local advance=to.s-from.s
          -- Sample the middle too: connected endpoints alone can hide a shortcut across a turn.
          -- Junction connectors can step sideways or a few metres backwards because the
          -- rendered road and GPS geometry are separate datasets. Permit only short joins;
          -- longer reversals and shortcuts still fail the direction/corridor checks.
          local connector = len<=20 and advance>=-5
          if math.max(from.off,to.off,mid.off)>M.CORRIDOR_M then
            diag.corridor=diag.corridor+1
          elseif not (len>0.1 and (advance>0.2*len or connector) and advance<=2*len+20) then
            diag.direction=diag.direction+1
          elseif to.s>here+ahead+80 then
            diag.horizon=diag.horizon+1
          else
            local deviation=(from.off^2+4*mid.off^2+to.off^2)/6
            local penalty=len*math.max(0,deviation-freeError^2)/64+math.max(0,len-advance)*2
            -- A preference must not turn an admissible forward road into a dead end.
            -- Previously a modest changing offset cost more than its forward progress,
            -- so the best endpoint stayed behind despite hundreds of metres of valid road.
            if advance>0.2*len then penalty=math.min(penalty,advance*0.5) end
            local nextCost=cost+penalty
            if costs[other]==nil or nextCost<costs[other] then
              costs[other],prev[other]=nextCost,id
              push(heap,other,nextCost)
            end
          end
        end
      end
    end
  end
  local reverse, id = {}, best
  while id do reverse[#reverse+1]=id; id=prev[id] end
  local ids={a}
  for i=#reverse,1,-1 do ids[#ids+1]=reverse[i] end
  local length=distance(pos,nodes[b].pos)
  for i=2,#ids-1 do length=length+distance(nodes[ids[i]].pos,nodes[ids[i+1]].pos) end
  local endpoint=at(best)
  -- Near a destination in XY is insufficient when its road still needs a ramp/loop to reach it.
  local final=e.cum[#e.cum]-endpoint.s<=40 and endpoint.off<=M.CORRIDOR_M
  diag.reason=final and 'destination' or 'local_endpoint'
  diag.endpoint,diag.length,diag.nodes=best,length,#ids
  return {ids=ids,s=endpoint.s,length=length,final=final},diag
end

return M
