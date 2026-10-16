-- Run from the addon root with Lua 5.1 or 5.2+.
-- Loads the stock AzerothCore corrections and then the live-server layer in
-- Database/IndividualProgression (tools/generate_ip_overlay.py), runs every registered
-- correction callback, and checks that the server's own data wins.
local function read(path)
    local file = assert(io.open(path, "rb"))
    local source = file:read("*a"):gsub("\r\n", "\n"):gsub("^\239\187\191", "")
    file:close()
    return source
end
local function equal(actual, expected, label)
    assert(actual == expected, label .. ": expected " .. tostring(expected) .. ", got " .. tostring(actual))
end
local env = setmetatable({}, {__index = _G})
env._G = env
local modules = {}
env.QuestieLoader = {
    ImportModule = function(_, name)
        modules[name] = modules[name] or {}
        return modules[name]
    end,
    StampLoadBoundary = function() end,
}
env.QuestieLoader.CreateModule = env.QuestieLoader.ImportModule
local function compile(source, label)
    if setfenv then return setfenv(assert(loadstring(source, label)), env) end
    return assert(load(source, label, "t", env))
end
local function loadModule(path) compile(read(path), "@" .. path)() end
local function loadEnum(path, declaration)
    local pattern = declaration:gsub("(%W)", "%%%1") .. " = %b{}"
    compile(assert(read(path):match(pattern), "missing enum: " .. declaration), "@" .. path)()
end

env.QuestieCompat = {}
env.QuestieDB = env.QuestieLoader:ImportModule("QuestieDB")
env.QuestieProfessions = env.QuestieLoader:ImportModule("QuestieProfessions")
local registered = {}
env.QuestieCompat.RegisterCorrection = function(dbName, callback)
    registered[#registered + 1] = {dbName, callback}
end
env.QuestieCompat.Merge = function(target, source)
    for id, fields in pairs(source) do
        target[id] = target[id] or {}
        for key, value in pairs(fields) do target[id][key] = value end
    end
    return target
end

local overlay = read("Database/IndividualProgression/IndividualProgression.xml")
local files = {}
for name in overlay:gmatch('<Script file="([^"]+)"') do files[#files + 1] = name end
assert(#files >= 1, "the overlay manifest lists its files")
assert(read("Questie-335.toc"):find("Database\\AzerothCore\\AzerothCore.xml\n.-Database\\IndividualProgression\\IndividualProgression.xml"),
    "the overlay loads after the stock AzerothCore corrections")

local manifest = read("Database/AzerothCore/AzerothCore.xml")
for name in manifest:gmatch('<Script file="([^"]+)"') do loadModule("Database/AzerothCore/" .. name) end
local stockCount = #registered
for _, name in ipairs(files) do loadModule("Database/IndividualProgression/" .. name) end
assert(#registered > stockCount, "the overlay registers corrections")

for _, name in ipairs({"quest", "npc", "item", "object"}) do loadModule("Database/" .. name .. "DB.lua") end
for _, name in ipairs({"raceKeys", "classKeys", "specialFlags"}) do
    loadEnum("Database/QuestieDB.lua", "QuestieDB." .. name)
end
loadEnum("Modules/QuestieProfessions.lua", "QuestieProfessions.professionKeys")
loadModule("Database/Zones/zoneTables.lua")
modules.ZoneDB.zoneIDs = modules.ZoneDB.private.zoneIDs

-- Apply in registration order, like QuestieCompat.LoadCorrections: later corrections win.
local data = {questData = {}, npcData = {}, itemData = {}, objectData = {}}
for index, entry in ipairs(registered) do
    local ok, corrections = pcall(entry[2])
    assert(ok, ("correction %d (%s) failed: %s"):format(index, entry[1], tostring(corrections)))
    for id, fields in pairs(corrections) do
        data[entry[1]][id] = data[entry[1]][id] or {}
        for key, value in pairs(fields) do data[entry[1]][id][key] = value end
    end
end

local questKeys = env.QuestieDB.questKeys
-- mod-individual-progression's own quest, unknown to Questie: a whole entry with its giver.
local gong = data.questData[108744]
assert(gong, "Chaos and Destruction (108744) is added")
equal(gong[questKeys.name], "Chaos and Destruction", "new quest name")
equal(gong[questKeys.startedBy][1][1], 15693, "new quest giver")
equal(gong[questKeys.zoneOrSort], 1377, "new quest zone")
-- Soothing Turtle Bisque needs the Soothing Spices too on the live server.
local bisque = data.questData[555][questKeys.objectives][3]
equal(#bisque, 2, "Soothing Turtle Bisque objectives")
local npcKeys = env.QuestieDB.npcKeys
-- mod-individual-progression's Horde Warbringer (the AQ war effort), unknown to Questie.
assert(data.npcData[115350] and data.npcData[115350][npcKeys.spawns], "Horde Warbringer (115350) has spawns")
-- An NPC the stock corrections change but the live server has as Questie does is set back.
equal(data.npcData[1505][npcKeys.factionID], 22, "stock NPC correction set back to Questie's data")
-- The server owner's test quests stay out.
for id in pairs(data.questData) do
    assert(not (id >= 90000 and id <= 99999), "test quest " .. id .. " is not in the overlay")
end
print("IndividualProgression overlay loading tests passed")
