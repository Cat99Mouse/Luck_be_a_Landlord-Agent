# LBALBOT_BRIDGE_BEGIN
var lbalbot_host = "127.0.0.1"
var lbalbot_port = 12346
var lbalbot_server = null
var lbalbot_clients = []
var lbalbot_buffers = {}

func lbalbot_setup():
	if lbalbot_server != null:
		return
	var env_host = OS.get_environment("LBALBOT_HOST")
	var env_port = OS.get_environment("LBALBOT_PORT")
	if env_host != "":
		lbalbot_host = env_host
	if env_port != "":
		lbalbot_port = int(env_port)
	lbalbot_server = TCP_Server.new()
	var err = lbalbot_server.listen(lbalbot_port, lbalbot_host)
	if err != OK:
		push_error("LBALBot failed to listen on " + lbalbot_host + ":" + str(lbalbot_port) + " err=" + str(err))
	else:
		print("LBALBot listening on http://" + lbalbot_host + ":" + str(lbalbot_port))

func lbalbot_poll():
	if lbalbot_server == null:
		return
	while lbalbot_server.is_connection_available():
		var peer = lbalbot_server.take_connection()
		peer.set_no_delay(true)
		lbalbot_clients.push_back(peer)
		lbalbot_buffers[peer.get_instance_id()] = PoolByteArray()
	var done = []
	for peer in lbalbot_clients:
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			done.push_back(peer)
			continue
		var available = peer.get_available_bytes()
		if available <= 0:
			continue
		var got = peer.get_data(available)
		if got[0] != OK:
			done.push_back(peer)
			continue
		var id = peer.get_instance_id()
		var buf = lbalbot_buffers[id]
		buf.append_array(got[1])
		lbalbot_buffers[id] = buf
		var req = lbalbot_try_parse_http(buf.get_string_from_utf8())
		if req != null:
			var response = lbalbot_handle_http(req)
			peer.put_data(response.to_utf8())
			peer.disconnect_from_host()
			done.push_back(peer)
	for peer in done:
		lbalbot_buffers.erase(peer.get_instance_id())
		lbalbot_clients.erase(peer)

func lbalbot_try_parse_http(raw):
	var header_end = raw.find("\r\n\r\n")
	if header_end == -1:
		return null
	var headers = raw.substr(0, header_end).split("\r\n")
	var length = 0
	for h in headers:
		var idx = h.find(":")
		if idx == -1:
			continue
		var key = h.substr(0, idx).strip_edges().to_lower()
		var val = h.substr(idx + 1, h.length()).strip_edges()
		if key == "content-length":
			length = int(val)
	var body_start = header_end + 4
	if raw.length() < body_start + length:
		return null
	return raw.substr(body_start, length)

func lbalbot_handle_http(body):
	var parsed = JSON.parse(body)
	var id = null
	if parsed.error != OK:
		return lbalbot_http_response(to_json({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error", "data": {"name": "PARSE_ERROR"}}, "id": id}))
	var req = parsed.result
	if typeof(req) != TYPE_DICTIONARY:
		return lbalbot_http_response(to_json({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid request", "data": {"name": "BAD_REQUEST"}}, "id": id}))
	if req.has("id"):
		id = req.id
	if not req.has("method"):
		return lbalbot_http_response(to_json({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Missing method", "data": {"name": "BAD_REQUEST"}}, "id": id}))
	var params = {}
	if req.has("params") and typeof(req.params) == TYPE_DICTIONARY:
		params = req.params
	var result = lbalbot_dispatch(str(req.method), params)
	if typeof(result) == TYPE_DICTIONARY and result.has("__lbalbot_error"):
		var e = result["__lbalbot_error"]
		return lbalbot_http_response(to_json({"jsonrpc": "2.0", "error": {"code": e["code"], "message": e["message"], "data": {"name": e["name"]}}, "id": id}))
	return lbalbot_http_response(to_json({"jsonrpc": "2.0", "result": result, "id": id}))

func lbalbot_http_response(body):
	return "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: " + str(body.to_utf8().size()) + "\r\nConnection: close\r\n\r\n" + body

func lbalbot_error(name, message, code):
	return {"__lbalbot_error": {"name": name, "message": message, "code": code}}

func lbalbot_debug_nodes(params):
	var keywords = ["storage", "inventory", "item", "items", "symbol", "symbols", "reel", "reels", "icon", "icons", "popup", "pop-up", "label"]
	if params.has("keywords") and typeof(params.keywords) == TYPE_ARRAY:
		keywords = []
		for k in params.keywords:
			keywords.push_back(str(k).to_lower())
	var max_depth = 10
	if params.has("max_depth"):
		max_depth = int(params.max_depth)
	var max_scan = 5000
	if params.has("max_scan"):
		max_scan = int(params.max_scan)
	var max_matches = 500
	if params.has("max_matches"):
		max_matches = int(params.max_matches)
	var matches = []
	var counters = {"scanned": 0, "matches": 0}
	lbalbot_debug_walk(get_tree().get_root(), 0, max_depth, max_scan, max_matches, keywords, matches, counters)
	var known = {}
	for path in ["Reels", "Items", "Pop-up Sprite/Pop-up", "Options Sprite/Options", "Buttons Menu"]:
		if has_node(path):
			var node = get_node(path)
			known[path] = lbalbot_debug_node_summary(node)
	return {
		"state": lbalbot_state_name(),
		"scanned": counters.scanned,
		"matched": counters.matches,
		"known": known,
		"inventory_icons_now": lbalbot_debug_icons(lbalbot_inventory_icons(), 30),
		"matches": matches
	}

func lbalbot_debug_node_props(params):
	if not params.has("path"):
		return lbalbot_error("BAD_REQUEST", "debug_node_props requires path", -32602)
	var node = lbalbot_debug_get_node(str(params.path))
	if node == null:
		return lbalbot_error("NOT_FOUND", "node not found: " + str(params.path), -32004)
	var requested = []
	if params.has("props") and typeof(params.props) == TYPE_ARRAY:
		for prop in params.props:
			requested.push_back(str(prop))
	else:
		requested = lbalbot_debug_property_names(node)
	var prop_names = lbalbot_debug_property_names(node)
	var values = {}
	var missing = []
	for prop in requested:
		if prop_names.has(prop):
			values[prop] = lbalbot_debug_value(node.get(prop), 3)
		else:
			missing.push_back(prop)
	return {
		"node": lbalbot_debug_node_summary(node),
		"values": values,
		"missing": missing
	}

func lbalbot_debug_call_node(params):
	if not params.has("path") or not params.has("method"):
		return lbalbot_error("BAD_REQUEST", "debug_call_node requires path and method", -32602)
	var method = str(params.method)
	var allowed = ["draw_deck", "undraw_deck", "draw_prompt_deck", "draw_removal_prompt"]
	if not allowed.has(method):
		return lbalbot_error("BAD_REQUEST", "debug_call_node method is not allowed: " + method, -32602)
	var node = lbalbot_debug_get_node(str(params.path))
	if node == null:
		return lbalbot_error("NOT_FOUND", "node not found: " + str(params.path), -32004)
	var args = []
	if params.has("args") and typeof(params.args) == TYPE_ARRAY:
		args = params.args
	match args.size():
		0:
			node.call(method)
		1:
			node.call(method, args[0])
		2:
			node.call(method, args[0], args[1])
		3:
			node.call(method, args[0], args[1], args[2])
		_:
			return lbalbot_error("BAD_REQUEST", "debug_call_node supports at most 3 args", -32602)
	return {
		"called": method,
		"node": lbalbot_debug_node_summary(node),
		"inventory_icons_now": lbalbot_debug_icons(lbalbot_inventory_icons(), 30)
	}

func lbalbot_debug_get_node(path):
	if has_node(path):
		return get_node(path)
	var root = get_tree().get_root()
	if root.has_node(path):
		return root.get_node(path)
	var root_prefix = str(root.get_path()) + "/"
	if str(path).begins_with(root_prefix):
		var relative = str(path).substr(root_prefix.length(), str(path).length())
		if root.has_node(relative):
			return root.get_node(relative)
	if str(path).begins_with("/root/"):
		var rel = str(path).substr(6, str(path).length())
		if root.has_node(rel):
			return root.get_node(rel)
	return null

func lbalbot_debug_walk(node, depth, max_depth, max_scan, max_matches, keywords, matches, counters):
	if node == null:
		return
	if counters.scanned >= max_scan or counters.matches >= max_matches:
		return
	counters.scanned += 1
	if lbalbot_debug_node_is_relevant(node, keywords):
		matches.push_back(lbalbot_debug_node_summary(node))
		counters.matches += 1
	if depth >= max_depth:
		return
	for child in node.get_children():
		lbalbot_debug_walk(child, depth + 1, max_depth, max_scan, max_matches, keywords, matches, counters)

func lbalbot_debug_node_is_relevant(node, keywords):
	var haystack = (str(node.name) + " " + str(node.get_path()) + " " + str(node.get_class())).to_lower()
	for keyword in keywords:
		if haystack.find(str(keyword).to_lower()) != -1:
			return true
	var prop_names = lbalbot_debug_property_names(node)
	for prop in ["item_types", "items", "icons", "icon_types", "label_text", "texts"]:
		if prop_names.has(prop):
			return true
	return false

func lbalbot_debug_node_summary(node):
	var prop_names = lbalbot_debug_property_names(node)
	var props = {}
	for prop in ["type", "item", "item_count", "item_types", "items", "icons", "icon_types", "label_text", "texts", "visible", "destroyable", "destroyed", "disabled", "button_text", "call", "args"]:
		if prop_names.has(prop):
			props[prop] = lbalbot_debug_value(node.get(prop), 2)
	return {
		"path": str(node.get_path()),
		"name": str(node.name),
		"class": str(node.get_class()),
		"child_count": node.get_child_count(),
		"prop_names": prop_names,
		"method_names": lbalbot_debug_method_names(node),
		"props": props
	}

func lbalbot_debug_property_names(node):
	var out = []
	for prop in node.get_property_list():
		if prop.has("name"):
			out.push_back(str(prop.name))
	return out

func lbalbot_debug_method_names(node):
	var out = []
	for method in node.get_method_list():
		if method.has("name"):
			out.push_back(str(method.name))
	return out

func lbalbot_debug_icons(icons, limit):
	var out = []
	var count = 0
	for icon in icons:
		if count >= limit:
			break
		if icon == null:
			continue
		out.push_back(lbalbot_debug_node_summary(icon))
		count += 1
	return {"count": icons.size(), "sample": out}

func lbalbot_debug_value(value, depth):
	var t = typeof(value)
	if t == TYPE_NIL or t == TYPE_BOOL or t == TYPE_INT or t == TYPE_REAL or t == TYPE_STRING:
		return value
	if t == TYPE_NODE_PATH:
		return str(value)
	if t == TYPE_VECTOR2 or t == TYPE_RECT2 or t == TYPE_VECTOR3 or t == TYPE_COLOR:
		return str(value)
	if t == TYPE_DICTIONARY:
		var keys_sample = []
		var sample = {}
		for key in value.keys():
			if keys_sample.size() >= 8:
				break
			keys_sample.push_back(str(key))
			if depth > 0:
				sample[str(key)] = lbalbot_debug_value(value[key], depth - 1)
		return {"kind": "Dictionary", "size": value.size(), "keys": keys_sample, "sample": sample}
	if t == TYPE_ARRAY:
		var sample = []
		if depth > 0:
			for i in range(min(value.size(), 8)):
				sample.push_back(lbalbot_debug_value(value[i], depth - 1))
		return {"kind": "Array", "size": value.size(), "sample": sample}
	if t == TYPE_OBJECT:
		if value == null:
			return null
		var out = {"kind": "Object", "class": str(value.get_class())}
		if value is Node:
			out["path"] = str(value.get_path())
			out["name"] = str(value.name)
		else:
			out["str"] = str(value)
		return out
	if str(value).length() > 200:
		return str(value).substr(0, 200)
	return str(value)

func lbalbot_dispatch(method, params):
	match method:
		"health":
			return {"status": "ok", "game": "luck_be_a_landlord", "version": version_str}
		"gamestate":
			return lbalbot_gamestate()
		"debug_nodes":
			return lbalbot_debug_nodes(params)
		"debug_node_props":
			return lbalbot_debug_node_props(params)
		"debug_call_node":
			return lbalbot_debug_call_node(params)
		"new_game":
			new_game()
			return lbalbot_gamestate()
		"continue_game":
			continue_game()
			return lbalbot_gamestate()
		"spin":
			if lbalbot_state_name() != "SLOTS":
				return lbalbot_error("INVALID_STATE", "spin requires SLOTS state", -32002)
			if not lbalbot_is_stable():
				return lbalbot_error("INVALID_STATE", "spin requires stable game state", -32002)
			$"Reels".spin()
			return lbalbot_gamestate()
		"remove_symbol":
			if not params.has("symbol"):
				return lbalbot_error("BAD_REQUEST", "remove_symbol requires symbol", -32602)
			return lbalbot_remove_symbol(params.symbol)
		"destroy_item":
			if not params.has("item"):
				return lbalbot_error("BAD_REQUEST", "destroy_item requires item", -32602)
			return lbalbot_destroy_item(params.item)
		"choose":
			if not params.has("choice"):
				return lbalbot_error("BAD_REQUEST", "choose requires choice", -32602)
			return lbalbot_choose(params.choice)
		"skip":
			return lbalbot_choose("skip")
		"reroll":
			return lbalbot_choose("reroll_pay")
		"button":
			var index = int(params.get("index", 0))
			return lbalbot_press_button(index)
		"confirm":
			return lbalbot_press_button(0)
		"save":
			save_game()
			return lbalbot_gamestate()
		"load":
			load_game()
			return lbalbot_gamestate()
		_:
			return lbalbot_error("METHOD_NOT_FOUND", "Unknown method: " + method, -32601)

func lbalbot_choose(choice):
	var popup = $"Pop-up Sprite/Pop-up"
	if not popup.visible or popup.emails.size() == 0:
		return lbalbot_error("INVALID_STATE", "choose requires an active popup event", -32002)
	popup.resolve_event(choice)
	return lbalbot_gamestate()

func lbalbot_press_button(index):
	var popup = $"Pop-up Sprite/Pop-up"
	var visible_buttons = []
	for b in popup.buttons:
		if b != null and b.visible:
			visible_buttons.push_back(b)
	if index < 0 or index >= visible_buttons.size():
		return lbalbot_error("BAD_REQUEST", "button index out of range", -32602)
	var button = visible_buttons[index]
	if button.call == "resolve_event":
		if button.args.size() > 0:
			popup.resolve_event(button.args[0])
		else:
			popup.resolve_event(null)
	else:
		match button.args.size():
			0:
				button.target.call(button.call)
			1:
				button.target.call(button.call, button.args[0])
			2:
				button.target.call(button.call, button.args[0], button.args[1])
			3:
				button.target.call(button.call, button.args[0], button.args[1], button.args[2])
	return lbalbot_gamestate()

func lbalbot_state_name():
	var popup = $"Pop-up Sprite/Pop-up"
	if $"Title".visible:
		return "TITLE"
	if $"Reels".spinning or $"Reels".effects_playing:
		return "SPINNING"
	if popup.visible and popup.emails.size() > 0:
		return str(popup.emails[0].type).to_upper()
	return "SLOTS"

func lbalbot_gamestate():
	var popup = $"Pop-up Sprite/Pop-up"
	var coins = $"Coins"
	var landlord = $"Landlord"
	var state_name = lbalbot_state_name()
	var stable = lbalbot_is_stable()
	var storage = lbalbot_empty_storage_snapshot()
	if state_name != "TITLE" and state_name != "SPINNING" and stable:
		storage = lbalbot_storage_snapshot()
	var state = {
		"state": state_name,
		"coins": coins.coins,
		"queued_coins": coins.queued_increase,
		"effective_coins": coins.coins + coins.queued_increase,
		"spins": popup.spins,
		"rent_values": popup.rent_values.duplicate(true),
		"times_rent_paid": popup.times_rent_paid,
		"times_to_pay_rent": popup.times_to_pay_rent,
		"reroll_tokens": popup.reroll_tokens,
		"removal_tokens": popup.removal_tokens,
		"removal_cost": popup.removal_cost,
		"essence_tokens": popup.essence_tokens,
		"current_floor": popup.current_floor,
		"landlord_hp": landlord.hp,
		"landlord_max_hp": landlord.max_hp,
		"symbols": lbalbot_symbols(),
		"symbol_inventory": lbalbot_symbol_inventory(storage),
		"items": lbalbot_items(storage),
		"removable_symbols": lbalbot_removable_symbols(storage),
		"destroyable_items": lbalbot_destroyable_items(),
		"choices": lbalbot_choices(),
		"buttons": lbalbot_buttons(),
		"stable": stable
	}
	if popup.emails.size() > 0:
		state["event"] = popup.emails[0].type
	return state

func lbalbot_is_stable():
	var popup = $"Pop-up Sprite/Pop-up"
	var coins = $"Coins"
	var popup_stable = (not popup.visible) or popup.offset_y == popup.offset_top
	return popup_stable and not $"Reels".spinning and not $"Reels".effects_playing and $"Landlord".anim_time <= 0 and not $"Sums/Coin Sum".adding and not $"Sums/HP Sum".adding and coins.queued_increase == 0

func lbalbot_symbols():
	var out = []
	for r in $"Reels".reels:
		out.push_back({"icon_types": r.icon_types.duplicate(true), "spinning": r.spinning})
	return out

func lbalbot_storage_snapshot():
	var popup = $"Pop-up Sprite/Pop-up"
	var opened_for_read = false
	if not popup.inv_open:
		popup.draw_deck()
		opened_for_read = true
	var snapshot = {
		"symbol_data": popup.saved_symbol_data.duplicate(true),
		"symbol_counts": popup.saved_symbol_counts.duplicate(true),
		"icons": lbalbot_storage_icon_entries(),
		"source": "storage_deck"
	}
	if opened_for_read and popup.inv_open:
		popup.undraw_deck()
	return snapshot

func lbalbot_empty_storage_snapshot():
	return {
		"symbol_data": [],
		"symbol_counts": {},
		"icons": [],
		"source": "unavailable"
	}

func lbalbot_storage_icon_entries():
	var out = []
	for icon in lbalbot_inventory_icons():
		if icon == null:
			continue
		var t = str(icon.get("type"))
		if t == "" or t == "empty":
			continue
		var entry = {
			"type": lbalbot_normalized_symbol_type(t),
			"item": icon.get("item") == true
		}
		out.push_back(entry)
	return out

func lbalbot_symbol_inventory(storage = null):
	if storage == null:
		storage = lbalbot_storage_snapshot()
	if storage == null:
		return []
	var counts = storage.get("symbol_counts", {})
	var out = []
	for data in storage.get("symbol_data", []):
		if typeof(data) != TYPE_DICTIONARY:
			continue
		var t = lbalbot_normalized_symbol_type(str(data.get("type", "")))
		if t == "" or t == "empty" or lbalbot_is_inventory_token(t):
			continue
		var entry = {
			"type": t,
			"count": lbalbot_storage_symbol_count(data, counts),
			"source": "storage_deck"
		}
		lbalbot_apply_storage_symbol_fields(entry, data)
		lbalbot_enrich_card_entry(entry, lbalbot_lookup_card_data(t), t)
		out.push_back(entry)
	return out

func lbalbot_storage_symbol_count(data, counts):
	var keys = [
		lbalbot_storage_symbol_key(data),
		str(data.get("type", ""))
	]
	for key in keys:
		if counts.has(key):
			return lbalbot_count_value(counts[key])
	return 1

func lbalbot_storage_symbol_key(data):
	return str(data.get("type", "")) + str(data.get("value_text", "")) + str(data.get("permanent_bonus", "")) + str(data.get("permanent_multiplier", ""))

func lbalbot_count_value(value):
	if typeof(value) == TYPE_DICTIONARY and value.has("count"):
		return int(value.count)
	if typeof(value) == TYPE_INT or typeof(value) == TYPE_REAL:
		return int(value)
	return 1

func lbalbot_apply_storage_symbol_fields(entry, data):
	for field in ["value_text", "permanent_bonus", "permanent_multiplier", "times_displayed"]:
		if data.has(field) and str(data[field]) != "":
			entry[field] = data[field]

func lbalbot_items(storage = null):
	var out = []
	var node = $"Items"
	for i in range(node.item_types.size()):
		var item = {"type": node.item_types[i]}
		lbalbot_enrich_card_entry(item, lbalbot_lookup_card_data(node.item_types[i]), node.item_types[i])
		if i < node.items.size() and node.items[i] != null:
			lbalbot_apply_item_node_fields(item, node.items[i])
		out.push_back(item)
	return out

func lbalbot_apply_item_runtime_fields(item, item_type):
	var node = $"Items"
	for i in range(node.items.size()):
		var item_node = node.items[i]
		if item_node != null and str(item_node.type) == str(item_type):
			lbalbot_apply_item_node_fields(item, item_node)
			return

func lbalbot_apply_item_node_fields(item, item_node):
	item["item_count"] = item_node.item_count
	item["destroyed"] = item_node.destroyed
	item["destroyable"] = item_node.destroyable
	item["manually_destroyable"] = item_node.get("manually_destroyable") == true
	item["can_be_destroyed_before_rent"] = item_node.get("can_be_destroyed_before_rent") == true
	item["disabled"] = item_node.disabled
	item["destroy_counters"] = item_node.destroy_counters

func lbalbot_removable_symbols(storage = null):
	var popup = $"Pop-up Sprite/Pop-up"
	if lbalbot_state_name() != "SLOTS":
		return []
	if popup.removal_tokens < popup.removal_cost:
		return []
	if storage == null:
		storage = lbalbot_storage_snapshot()
	var out = []
	for symbol in lbalbot_symbol_inventory(storage):
		var t = str(symbol.get("type", ""))
		if not lbalbot_can_remove_symbol(t):
			continue
		var entry = symbol.duplicate(true)
		entry["removal_cost"] = popup.removal_cost
		out.push_back(entry)
	return out

func lbalbot_normalized_symbol_type(symbol_type):
	var t = str(symbol_type)
	if t == "hover_coin":
		return "coin"
	return t

func lbalbot_is_inventory_token(symbol_type):
	var t = str(symbol_type)
	return t == "essence_token" or t == "reroll_token" or t == "removal_token"

func lbalbot_can_remove_symbol(symbol_type):
	var t = str(symbol_type)
	if t == "hover_coin":
		t = "coin"
	if t == "" or t == "empty":
		return false
	var q = load("res://Slot Icon.tscn").instance()
	q.type = t
	q.in_reels = false
	add_child(q)
	q.soft_changing = true
	q.change_type(q.type, false)
	var ok = q.can_be_removed
	remove_child(q)
	q.queue_free()
	return ok

func lbalbot_destroyable_items():
	if lbalbot_state_name() != "SLOTS":
		return []
	var out = []
	var node = $"Items"
	for i in range(node.items.size()):
		var item_node = node.items[i]
		if not lbalbot_can_manually_destroy_item_node(item_node):
			continue
		var item = {
			"type": item_node.type,
			"index": i,
			"count": item_node.item_count,
			"destroy_counters": item_node.destroy_counters,
			"destroyable": item_node.destroyable,
			"manually_destroyable": item_node.get("manually_destroyable") == true,
			"can_be_destroyed_before_rent": item_node.get("can_be_destroyed_before_rent") == true,
			"disabled": item_node.disabled
		}
		lbalbot_enrich_card_entry(item, lbalbot_lookup_card_data(item_node.type), item_node.type)
		out.push_back(item)
	return out

func lbalbot_can_manually_destroy_item_node(item_node):
	return item_node != null and item_node.destroyable and item_node.get("manually_destroyable") == true and not item_node.destroyed and not item_node.disabled

func lbalbot_remove_symbol(symbol_type):
	if lbalbot_state_name() != "SLOTS":
		return lbalbot_error("INVALID_STATE", "remove_symbol requires SLOTS state", -32002)
	var popup = $"Pop-up Sprite/Pop-up"
	if popup.removal_tokens < popup.removal_cost:
		return lbalbot_error("NO_REMOVAL_TOKEN", "not enough removal tokens", -32003)
	var target = str(symbol_type)
	if target == "" or target == "empty":
		return lbalbot_error("BAD_REQUEST", "invalid symbol type", -32602)
	if not lbalbot_can_remove_symbol(target):
		return lbalbot_error("NOT_REMOVABLE", "symbol cannot be removed: " + target, -32004)
	popup.draw_removal_prompt(true)
	var icon = lbalbot_find_inventory_symbol_icon(target)
	if icon == null:
		if popup.emails.size() > 0 and popup.emails[0].type == "removal_token_prompt":
			popup.resolve_event("<icon_deny>")
		return lbalbot_error("NOT_FOUND", "symbol not found in inventory: " + target, -32004)
	icon.press()
	return lbalbot_gamestate()

func lbalbot_find_inventory_symbol_icon(symbol_type):
	var target = str(symbol_type)
	if target == "hover_coin":
		target = "coin"
	var icons = lbalbot_inventory_icons()
	for icon in icons:
		if icon == null:
			continue
		var t = str(icon.type)
		if t == "hover_coin":
			t = "coin"
		if t == target and not icon.item:
			return icon
	return null

func lbalbot_inventory_icons():
	var popup = $"Pop-up Sprite/Pop-up"
	if popup.label_text == null:
		return []
	if $"Options Sprite/Options".CJK_lang or int($"Options Sprite/Options".display_font) > 0:
		if popup.label_text.get_child_count() > 0:
			return popup.label_text.get_child(0).icons
	else:
		if popup.label_text.texts.size() > 8:
			return popup.label_text.texts[8].icons
	return []

func lbalbot_destroy_item(item_type):
	if lbalbot_state_name() != "SLOTS":
		return lbalbot_error("INVALID_STATE", "destroy_item requires SLOTS state", -32002)
	var target = str(item_type)
	if target == "":
		return lbalbot_error("BAD_REQUEST", "invalid item type", -32602)
	for item in $"Items".items:
		if item == null:
			continue
		if str(item.type) == target and lbalbot_can_manually_destroy_item_node(item):
			item.destroy()
			save_game()
			return lbalbot_gamestate()
	return lbalbot_error("NOT_FOUND", "destroyable item not found: " + target, -32004)

func lbalbot_choices():
	var popup = $"Pop-up Sprite/Pop-up"
	var out = []
	for c in popup.cards:
		if c == null or c.data == null:
			continue
		var data = c.data
		var choice = {"type": data.type}
		lbalbot_enrich_card_entry(choice, data, data.type)
		out.push_back(choice)
	return out

func lbalbot_lookup_card_data(card_type):
	var t = str(card_type)
	if tile_database.has(t):
		return tile_database[t]
	if item_database.has(t):
		return item_database[t]
	if t.find("_STEAM_ID_") != -1:
		var base = t.substr(0, t.find("_STEAM_ID_"))
		if tile_database.has(base):
			return tile_database[base]
		if item_database.has(base):
			return item_database[base]
	return null

func lbalbot_enrich_card_entry(entry, data, fallback_type):
	if data == null:
		entry["name"] = lbalbot_localized_name({}, fallback_type)
		var fallback_desc = lbalbot_localized_description({}, fallback_type)
		if fallback_desc != "":
			entry["description_raw"] = fallback_desc
			entry["description"] = lbalbot_plain_text(fallback_desc, null)
		return
	entry["name"] = lbalbot_localized_name(data, fallback_type)
	var desc = lbalbot_localized_description(data, fallback_type)
	if desc != "":
		entry["description_raw"] = desc
		entry["description"] = lbalbot_plain_text(desc, data)
	if data.has("display_name"):
		entry["display_name"] = data.display_name
	if data.has("rarity"):
		entry["rarity"] = data.rarity
	if data.has("value"):
		entry["value"] = data.value
	if data.has("values"):
		entry["values"] = data.values.duplicate(true)
	if data.has("groups"):
		entry["groups"] = data.groups.duplicate(true)

func lbalbot_localized_name(data, fallback_type):
	var t = str(fallback_type)
	if data.has("type"):
		t = str(data.type)
	if t == "":
		return ""
	if data.has("modded") and data.modded:
		if data.has("localized_names") and data.localized_names.has(TranslationServer.get_locale()):
			return data.localized_names[TranslationServer.get_locale()]
		if data.has("display_name"):
			return data.display_name
	if data.has("rarity") and data.rarity == "essence":
		var base = t.substr(0, t.length() - 8)
		var localized_base = tr(base)
		if localized_base != base:
			return localized_base
	var localized = tr(t)
	if localized == t:
		return ""
	return localized

func lbalbot_localized_description(data, fallback_type):
	var t = str(fallback_type)
	if data.has("type"):
		t = str(data.type)
	if t == "":
		return ""
	var desc = ""
	if t == "essence_token" or t == "reroll_token" or t == "removal_token":
		desc = tr(t + "_reminder")
	elif data.has("modded") and data.modded:
		if data.has("localized_descriptions") and data.localized_descriptions.has(TranslationServer.get_locale()):
			desc = data.localized_descriptions[TranslationServer.get_locale()]
		elif data.has("description"):
			desc = data.description
		if data.has("inherit_description") and data.inherit_description and data.has("inherit_effects") and data.inherit_effects:
			var inherited_type = t.substr(0, t.find("_STEAM_ID_"))
			var inherited_desc = tr(inherited_type + "_desc")
			if inherited_desc == inherited_type + "_desc":
				inherited_desc = ""
			if inherited_desc != "":
				if desc == "":
					desc = inherited_desc
				else:
					desc = inherited_desc + "\n" + desc
	else:
		desc = tr(t + "_desc")
	if desc == t + "_desc" or desc == t + "_reminder":
		return ""
	return desc

func lbalbot_plain_text(raw, data):
	var out = str(raw)
	if data != null and data.has("values"):
		for i in range(data.values.size()):
			out = out.replace("<value_" + str(i + 1) + ">", str(data.values[i]))
	out = lbalbot_replace_markup_tags(out)
	return out.strip_edges()

func lbalbot_replace_markup_tags(text):
	var out = str(text)
	while out.find("<") != -1:
		var start = out.find("<")
		var end = out.find(">", start)
		if end == -1:
			break
		var tag = out.substr(start + 1, end - start - 1)
		var replacement = ""
		if tag == "end" or tag == "text_color_keyword" or tag.begins_with("color_"):
			replacement = ""
		elif tag.begins_with("group_") or tag.begins_with("last_"):
			replacement = " " + lbalbot_group_tag_text(tag) + " "
		elif tag.begins_with("icon_"):
			replacement = " " + tag.substr(5, tag.length()).replace("_", " ") + " "
		else:
			replacement = " " + tag.replace("_", " ") + " "
		out = out.substr(0, start) + replacement + out.substr(end + 1, out.length())
	while out.find("  ") != -1:
		out = out.replace("  ", " ")
	return out

func lbalbot_group_tag_text(tag):
	var only_last = tag.begins_with("last_")
	var group_name = ""
	var group_kind = "symbols"
	if tag.begins_with("group_item_"):
		group_kind = "items"
		group_name = tag.substr(11, tag.length())
	elif tag.begins_with("last_item_"):
		group_kind = "items"
		group_name = tag.substr(10, tag.length())
	elif tag.begins_with("group_"):
		group_name = tag.substr(6, tag.length())
	elif tag.begins_with("last_"):
		group_name = tag.substr(5, tag.length())
	if group_name == "":
		return tag.replace("_", " ")
	if not group_database.has(group_kind) or not group_database[group_kind].has(group_name):
		return group_name.replace("_", " ")

	var group_arr = group_database[group_kind][group_name]
	if group_arr.size() == 0:
		return group_name.replace("_", " ")

	var selected = []
	if only_last:
		selected.push_back(group_arr[group_arr.size() - 1])
	else:
		var limit = group_arr.size()
		if group_arr.size() > 1:
			limit -= 1
		for i in range(limit):
			selected.push_back(group_arr[i])
	return lbalbot_join_card_refs(selected)

func lbalbot_join_card_refs(types):
	var parts = []
	for t in types:
		parts.push_back(lbalbot_card_ref(t))
	return PoolStringArray(parts).join(", ")

func lbalbot_card_ref(card_type):
	var t = str(card_type)
	var data = lbalbot_lookup_card_data(t)
	var name = lbalbot_localized_name(data if data != null else {}, t)
	if name != "" and name != t:
		return name + "(" + t + ")"
	return t

func lbalbot_buttons():
	var popup = $"Pop-up Sprite/Pop-up"
	var out = []
	for b in popup.buttons:
		if b == null or not b.visible:
			continue
		out.push_back({"text": b.button_text, "call": b.call, "args": b.args.duplicate(true)})
	return out
# LBALBOT_BRIDGE_END
