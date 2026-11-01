#include "capture_view.hpp"
#include "obs_events.hpp"

#include <obs-frontend-api.h>

#include <QGridLayout>
#include <QLabel>
#include <QPushButton>
#include <QTimer>

static QString fmt(const QDateTime &start)
{
	const qint64 s = qMax<qint64>(0, start.secsTo(QDateTime::currentDateTime()));
	return QString("%1:%2:%3")
		.arg(s / 3600, 2, 10, QChar('0'))
		.arg((s / 60) % 60, 2, 10, QChar('0'))
		.arg(s % 60, 2, 10, QChar('0'));
}

CaptureView::CaptureView(QWidget *parent) : QWidget(parent)
{
	auto *grid = new QGridLayout(this);
	grid->setContentsMargins(6, 6, 6, 6);
	grid->setSpacing(6);

	auto mk = [this](const QString &t) {
		auto *b = new QPushButton(t, this);
		b->setMinimumHeight(30);
		return b;
	};
	rec_ = mk("Record");
	pause_ = mk("Pause");
	replay_ = mk("Instant Replay");
	saveReplay_ = mk("Save Replay");
	live_ = mk("Go live");
	vcam_ = mk("Virtual cam");
	shot_ = mk("Screenshot");
	info_ = new QLabel("Idle", this);

	grid->addWidget(rec_, 0, 0);
	grid->addWidget(pause_, 0, 1);
	grid->addWidget(replay_, 1, 0);
	grid->addWidget(saveReplay_, 1, 1);
	grid->addWidget(live_, 2, 0);
	grid->addWidget(vcam_, 2, 1);
	grid->addWidget(shot_, 3, 0, 1, 2);
	grid->addWidget(info_, 4, 0, 1, 2);

	connect(rec_, &QPushButton::clicked, this, [] {
		if (obs_frontend_recording_active())
			obs_frontend_recording_stop();
		else
			obs_frontend_recording_start();
	});
	connect(pause_, &QPushButton::clicked, this,
		[] { obs_frontend_recording_pause(!obs_frontend_recording_paused()); });
	connect(replay_, &QPushButton::clicked, this, [] {
		if (obs_frontend_replay_buffer_active())
			obs_frontend_replay_buffer_stop();
		else
			obs_frontend_replay_buffer_start();
	});
	connect(saveReplay_, &QPushButton::clicked, this, [] { obs_frontend_replay_buffer_save(); });
	connect(live_, &QPushButton::clicked, this, [] {
		if (obs_frontend_streaming_active())
			obs_frontend_streaming_stop();
		else
			obs_frontend_streaming_start();
	});
	connect(vcam_, &QPushButton::clicked, this, [] {
		if (obs_frontend_virtualcam_active())
			obs_frontend_stop_virtualcam();
		else
			obs_frontend_start_virtualcam();
	});
	connect(shot_, &QPushButton::clicked, this, [] { obs_frontend_take_screenshot(); });

	connect(&ObsEvents::instance(), &ObsEvents::stateChanged, this, &CaptureView::refresh);

	auto *t = new QTimer(this);
	t->setInterval(1000);
	connect(t, &QTimer::timeout, this, &CaptureView::tick);
	t->start();

	refresh();
}

void CaptureView::refresh()
{
	const bool rec = obs_frontend_recording_active();
	const bool paused = rec && obs_frontend_recording_paused();
	const bool live = obs_frontend_streaming_active();
	const bool rb = obs_frontend_replay_buffer_active();
	const bool vc = obs_frontend_virtualcam_active();

	if (rec && !wasRec_)
		recStart_ = QDateTime::currentDateTime();
	if (live && !wasLive_)
		liveStart_ = QDateTime::currentDateTime();
	wasRec_ = rec;
	wasLive_ = live;

	rec_->setText(rec ? "Stop recording" : "Record");
	pause_->setEnabled(rec);
	pause_->setText(paused ? "Resume" : "Pause");
	replay_->setText(rb ? "Instant Replay: ON" : "Instant Replay: OFF");
	saveReplay_->setEnabled(rb);
	live_->setText(live ? "Stop stream" : "Go live");
	vcam_->setText(vc ? "Virtual cam: ON" : "Virtual cam: OFF");
	tick();
}

void CaptureView::tick()
{
	QStringList parts;
	if (wasRec_)
		parts << QString("REC %1%2").arg(fmt(recStart_), obs_frontend_recording_paused() ? " (paused)" : "");
	if (wasLive_)
		parts << QString("LIVE %1").arg(fmt(liveStart_));
	info_->setText(parts.isEmpty() ? "Idle" : parts.join("   |   "));
}
