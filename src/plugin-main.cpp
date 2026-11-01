#include <obs-module.h>
#include <obs-frontend-api.h>

#include <QAction>
#include <QMetaObject>

#include "obs_events.hpp"
#include "overlay_panel.hpp"

OBS_DECLARE_MODULE()
OBS_MODULE_AUTHOR("ordinalkurdi")

const char *obs_module_name(void)
{
	return "OBS Overlay Panel";
}

const char *obs_module_description(void)
{
	return "Slide-out, always-on-top control panel with modular docks, built into OBS.";
}

static OverlayPanel *g_panel = nullptr;
static obs_hotkey_id g_toggleHotkey = OBS_INVALID_HOTKEY_ID;
static const char *kHotkeyKey = "obs_overlay_panel_toggle";

// Runs on OBS's hotkey thread: hop to the UI thread via a long-lived QObject.
static void onHotkey(void *, obs_hotkey_id, obs_hotkey_t *, bool pressed)
{
	if (pressed)
		QMetaObject::invokeMethod(&ObsEvents::instance(), "requestToggle", Qt::QueuedConnection);
}

// Persists the hotkey binding in the scene collection, like OBS's own hotkeys.
// A first run with no stored binding gets Alt+Z (rebind in Settings > Hotkeys).
static void saveLoad(obs_data_t *data, bool saving, void *)
{
	if (g_toggleHotkey == OBS_INVALID_HOTKEY_ID)
		return;

	if (saving) {
		obs_data_array_t *arr = obs_hotkey_save(g_toggleHotkey);
		obs_data_set_array(data, kHotkeyKey, arr);
		obs_data_array_release(arr);
		return;
	}

	obs_data_array_t *arr = obs_data_get_array(data, kHotkeyKey);
	if (arr) {
		obs_hotkey_load(g_toggleHotkey, arr);
		obs_data_array_release(arr);
		return;
	}

	obs_data_array_t *def = obs_data_array_create();
	obs_data_t *item = obs_data_create();
	obs_data_set_string(item, "key", "OBS_KEY_Z");
	obs_data_set_bool(item, "alt", true);
	obs_data_array_push_back(def, item);
	obs_hotkey_load(g_toggleHotkey, def);
	obs_data_release(item);
	obs_data_array_release(def);
}

bool obs_module_load(void)
{
	ObsEvents &ev = ObsEvents::instance();
	ev.start();

	g_toggleHotkey = obs_hotkey_register_frontend(kHotkeyKey, "Overlay Panel: show / hide", onHotkey, nullptr);
	obs_frontend_add_save_callback(saveLoad, nullptr);

	// Build the UI once OBS's main window is ready.
	QObject::connect(&ev, &ObsEvents::finishedLoading, &ev, [] {
		if (g_panel)
			return;
		g_panel = new OverlayPanel;
		auto *act = static_cast<QAction *>(obs_frontend_add_tools_menu_qaction("Overlay Panel"));
		QObject::connect(act, &QAction::triggered, g_panel, &OverlayPanel::toggle);
	});

	QObject::connect(&ev, &ObsEvents::exiting, &ev, [] {
		delete g_panel;
		g_panel = nullptr;
	});

	return true;
}

void obs_module_unload(void)
{
	ObsEvents::instance().stop();
	obs_frontend_remove_save_callback(saveLoad, nullptr);
}
