#pragma once

#include <QDateTime>
#include <QWidget>

class QLabel;
class QPushButton;

// Port of the "Capture" tab: recording, instant replay, streaming, virtual cam, screenshot.
// Talks to OBS directly through obs-frontend-api (no WebSocket).
class CaptureView : public QWidget {
	Q_OBJECT
public:
	explicit CaptureView(QWidget *parent = nullptr);

private slots:
	void refresh();
	void tick();

private:
	QPushButton *rec_, *pause_, *replay_, *saveReplay_, *live_, *vcam_, *shot_;
	QLabel *info_;
	QDateTime recStart_, liveStart_;
	bool wasRec_ = false, wasLive_ = false;
};
