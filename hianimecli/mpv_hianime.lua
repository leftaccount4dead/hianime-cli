local mp = require "mp"
local msg = require "mp.msg"
local utils = require "mp.utils"

local progress_file = os.getenv("HIANIME_PROGRESS_FILE")
local skip_intro = os.getenv("HIANIME_SKIP_INTRO") == "1"
local skip_outro = os.getenv("HIANIME_SKIP_OUTRO") == "1"
local intro_spans = {}
local outro_spans = {}
local intro_skipped = {}
local outro_skipped = {}
local last_position = nil

local function load_spans(name)
    local raw = os.getenv(name)
    if not raw or raw == "" then
        return {}
    end
    local ok, decoded = pcall(utils.parse_json, raw)
    if not ok or type(decoded) ~= "table" then
        return {}
    end
    local spans = {}
    for _, span in ipairs(decoded) do
        if type(span) == "table" then
            local start_time = tonumber(span[1] or span.start)
            local end_time = tonumber(span[2] or span["end"])
            if start_time and end_time and start_time >= 0 and end_time > start_time then
                spans[#spans + 1] = { start_time, end_time }
            end
        end
    end
    return spans
end

intro_spans = load_spans("HIANIME_INTROS")
outro_spans = load_spans("HIANIME_OUTROS")

local function valid_span(start_time, end_time)
    local duration = mp.get_property_number("duration")
    return start_time and end_time and duration
        and start_time >= 0 and end_time > start_time
        and end_time < duration - 2
end

local function write_position(position)
    if not progress_file or not position then
        return
    end
    local temporary = progress_file .. ".tmp"
    local file = io.open(temporary, "w")
    if not file then
        return
    end
    file:write(string.format("%.2f\n", position))
    file:close()
    os.rename(temporary, progress_file)
end

local function remove_position()
    if progress_file then
        os.remove(progress_file)
        os.remove(progress_file .. ".tmp")
    end
end

local function save_progress()
    local position = mp.get_property_number("time-pos")
    if not position then
        return
    end
    write_position(position)
end

local function skip_crossed_span(spans, skipped, position, label, initial)
    for index, span in ipairs(spans) do
        local start_time, end_time = span[1], span[2]
        local crossed = last_position and last_position < start_time
            and position >= start_time and position < end_time
        local begins_at_start = initial and start_time == 0
            and position >= start_time and position < end_time
        if not skipped[index] and valid_span(start_time, end_time)
            and (crossed or begins_at_start) then
            skipped[index] = true
            mp.osd_message("Skipping " .. label, 2)
            msg.info("Skipping " .. label .. " at " .. tostring(start_time) .. "s")
            last_position = end_time
            mp.commandv("seek", tostring(end_time), "absolute+exact")
            return true
        end
    end
    return false
end

local function on_time_pos(_, position)
    if not position then
        last_position = nil
        return
    end
    local initial = last_position == nil
    if initial then
        last_position = position
    end
    if skip_intro and skip_crossed_span(
        intro_spans, intro_skipped, position, "intro", initial
    ) then
        return
    end
    if skip_outro then
        skip_crossed_span(outro_spans, outro_skipped, position, "outro", false)
    end
    last_position = position
end

mp.observe_property("time-pos", "number", on_time_pos)
mp.add_periodic_timer(0.1, function()
    on_time_pos(nil, mp.get_property_number("time-pos"))
end)
mp.add_periodic_timer(3, save_progress)
mp.register_event("end-file", function(event)
    if event.reason == "eof" then
        remove_position()
    end
end)
