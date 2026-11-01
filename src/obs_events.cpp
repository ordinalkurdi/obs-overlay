#include "obs_events.hpp"

#include <QMetaObject>

ObsEvents &ObsEvents::instance()
{
	static ObsEvents *g = new ObsEvents; // lives for the whole OBS session
	return *g;
}

void ObsEvents::start()
{
	obs_frontend_add_event_callback(&ObsEvents::callback, this);
}

void ObsEvents::stop()
{
	obs_frontend_remove_event_callback(&ObsEvents::callback, this);
}

void ObsEvents::callback(enum obs_frontend_event event, void *priv)
{
	auto *self = static_cast<ObsEvents *>(priv);

	auto post = [self](void (ObsEvents::*sig)()) {
		QMetaObject::invokeMethod(self, [self, sig] { (self->*sig)(); }, Qt::QueuedConnection);
	};

	switch (event) {
	case OBS_FRONTEND_EVENT_FINISHED_LOADING:
		post(&ObsEvents::finishedLoading);
		post(&ObsEvents::scenesChanged);
		post(&ObsEvents::stateChanged);
		break;

	case OBS_FRONTEND_EVENT_STREAMING_STARTING:
	case OBS_FRONTEND_EVENT_STREAMING_STARTED:
	case OBS_FRONTEND_EVENT_STREAMING_STOPPING:
	case OBS_FRONTEND_EVENT_STREAMING_STOPPED:
	case OBS_FRONTEND_EVENT_RECORDING_STARTING:
	case OBS_FRONTEND_EVENT_RECORDING_STARTED:
	case OBS_FRONTEND_EVENT_RECORDING_STOPPING:
	case OBS_FRONTEND_EVENT_RECORDING_STOPPED:
	case OBS_FRONTEND_EVENT_RECORDING_PAUSED:
	case OBS_FRONTEND_EVENT_RECORDING_UNPAUSED:
	case OBS_FRONTEND_EVENT_REPLAY_BUFFER_STARTED:
	case OBS_FRONTEND_EVENT_REPLAY_BUFFER_STOPPED:
	case OBS_FRONTEND_EVENT_REPLAY_BUFFER_SAVED:
	case OBS_FRONTEND_EVENT_SCREENSHOT_TAKEN:
	case OBS_FRONTEND_EVENT_VIRTUALCAM_STARTED:
	case OBS_FRONTEND_EVENT_VIRTUALCAM_STOPPED:
		post(&ObsEvents::stateChanged);
		break;

	case OBS_FRONTEND_EVENT_SCENE_CHANGED:
	case OBS_FRONTEND_EVENT_SCENE_LIST_CHANGED:
	case OBS_FRONTEND_EVENT_SCENE_COLLECTION_CHANGED:
		post(&ObsEvents::scenesChanged);
		break;

	case OBS_FRONTEND_EVENT_EXIT:
		// Direct: the panel must be destroyed before Qt is torn down.
		emit self->exiting();
		break;

	default:
		break;
	}
}
