#pragma once

#include <QObject>
#include <obs-frontend-api.h>

// Bridges obs-frontend-api callbacks (any thread) to Qt signals (UI thread).
class ObsEvents : public QObject {
	Q_OBJECT
public:
	static ObsEvents &instance();
	void start();
	void stop();

	// Called from the OBS hotkey thread.
	Q_INVOKABLE void requestToggle() { emit toggleRequested(); }

signals:
	void finishedLoading();
	void stateChanged();  // record / stream / replay buffer / virtual cam
	void scenesChanged(); // scene list or current scene
	void toggleRequested();
	void exiting();

private:
	static void callback(enum obs_frontend_event event, void *priv);
};
