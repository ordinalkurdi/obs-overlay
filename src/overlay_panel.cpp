#include "overlay_panel.hpp"
#include "capture_view.hpp"
#include "gallery_view.hpp"
#include "obs_events.hpp"
#include "plugin_settings.hpp"
#include "scenes_view.hpp"

#include <obs-frontend-api.h>
#include <obs-module.h>

#include <QAction>
#include <QActionGroup>
#include <QCursor>
#include <QDir>
#include <QDockWidget>
#include <QGuiApplication>
#include <QHBoxLayout>
#include <QLabel>
#include <QMainWindow>
#include <QMenu>
#include <QPainter>
#include <QPropertyAnimation>
#include <QPushButton>
#include <QScreen>
#include <QSettings>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

static QToolButton *makeBtn(const QString &text, const QString &tip, QWidget *parent)
{
	auto *b = new QToolButton(parent);
	b->setText(text);
	b->setToolTip(tip);
	b->setAutoRaise(true);
	return b;
}

OverlayPanel::OverlayPanel(QWidget *parent)
	: QWidget(parent, Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint)
{
	setObjectName("obsOverlayPanel");
	setAttribute(Qt::WA_ShowWithoutActivating);
	setAutoFillBackground(true);

	screen_ = QGuiApplication::primaryScreen();
	loadSettings();
	buildUi();
	setWindowOpacity(opacity_);

	anim_ = new QPropertyAnimation(this, "pos", this);
	anim_->setDuration(200);
	anim_->setEasingCurve(QEasingCurve::OutCubic);
	connect(anim_, &QPropertyAnimation::finished, this, [this] {
		if (!shown_)
			hide();
	});

	poll_ = new QTimer(this);
	poll_->setInterval(60);
	connect(poll_, &QTimer::timeout, this, &OverlayPanel::pollCursor);
	poll_->start();

	connect(&ObsEvents::instance(), &ObsEvents::toggleRequested, this, &OverlayPanel::toggle);
}

OverlayPanel::~OverlayPanel()
{
	saveSettings();
}

void OverlayPanel::buildUi()
{
	auto *root = new QVBoxLayout(this);
	root->setContentsMargins(6, 6, 6, 6);
	root->setSpacing(4);

	auto *bar = new QHBoxLayout;
	auto *title = new QLabel("OBS Overlay", this);
	title->setStyleSheet("font-weight: 600;");
	pinBtn_ = makeBtn("Pin", "Keep the panel open", this);
	pinBtn_->setCheckable(true);
	pinBtn_->setChecked(pinned_);
	connect(pinBtn_, &QToolButton::toggled, this, [this](bool on) {
		pinned_ = on;
		saveSettings();
	});
	auto *gear = makeBtn("Menu", "Overlay menu", this);
	gear->setPopupMode(QToolButton::InstantPopup);
	auto *close = makeBtn("X", "Hide", this);
	connect(close, &QToolButton::clicked, this, &OverlayPanel::slideOut);
	bar->addWidget(title, 1);
	bar->addWidget(pinBtn_);
	bar->addWidget(gear);
	bar->addWidget(close);
	root->addLayout(bar);

	// Modular area: an embedded QMainWindow whose dock widgets can be dragged,
	// stacked, tabbed and hidden. Floating is disabled so docks can't fall
	// behind a fullscreen game.
	host_ = new QMainWindow(this);
	host_->setWindowFlags(Qt::Widget);
	host_->setDockOptions(QMainWindow::AllowTabbedDocks | QMainWindow::AllowNestedDocks |
			      QMainWindow::AnimatedDocks);
	auto *central = new QWidget(host_);
	host_->setCentralWidget(central);
	central->hide(); // docks fill the whole area

	auto addDock = [this](const QString &name, QWidget *w) {
		auto *d = new QDockWidget(name, host_);
		d->setObjectName("dock_" + name);
		d->setFeatures(QDockWidget::DockWidgetMovable | QDockWidget::DockWidgetClosable);
		d->setWidget(w);
		host_->addDockWidget(Qt::LeftDockWidgetArea, d);
		return d;
	};
	addDock("Capture", new CaptureView(this));
	QDockWidget *scenes = addDock("Scenes", new ScenesView(this));
	QDockWidget *gallery = addDock("Gallery", new GalleryView(this));
	host_->tabifyDockWidget(scenes, gallery); // default layout; restoreState() below overrides it
	scenes->raise();
	root->addWidget(host_, 1);

	gear->setMenu(buildMenu());

	QSettings s = openSettings();
	const QByteArray state = s.value("dockState").toByteArray();
	if (!state.isEmpty())
		host_->restoreState(state);
}

QMenu *OverlayPanel::buildMenu()
{
	auto *m = new QMenu(this);

	m->addAction("Open OBS Settings...", this, [] { openObsSettings(); });
	m->addSeparator();

	auto *edgeMenu = m->addMenu("Dock to");
	auto *edgeGroup = new QActionGroup(edgeMenu);
	for (auto [label, e] : {std::pair{"Left edge", Edge::Left}, std::pair{"Right edge", Edge::Right}}) {
		QAction *a = edgeMenu->addAction(label);
		a->setCheckable(true);
		a->setChecked(edge_ == e);
		edgeGroup->addAction(a);
		connect(a, &QAction::triggered, this, [this, e] {
			edge_ = e;
			applyGeometryIfShown();
			saveSettings();
		});
	}

	auto *widthMenu = m->addMenu("Width");
	auto *widthGroup = new QActionGroup(widthMenu);
	for (int w : {320, 380, 460}) {
		QAction *a = widthMenu->addAction(QString::number(w) + " px");
		a->setCheckable(true);
		a->setChecked(width_ == w);
		widthGroup->addAction(a);
		connect(a, &QAction::triggered, this, [this, w] {
			width_ = w;
			applyGeometryIfShown();
			saveSettings();
		});
	}

	auto *opMenu = m->addMenu("Opacity");
	auto *opGroup = new QActionGroup(opMenu);
	for (int pct : {100, 90, 80, 70, 60}) {
		QAction *a = opMenu->addAction(QString::number(pct) + "%");
		a->setCheckable(true);
		a->setChecked(qRound(opacity_ * 100) == pct);
		opGroup->addAction(a);
		connect(a, &QAction::triggered, this, [this, pct] {
			opacity_ = pct / 100.0;
			setWindowOpacity(opacity_);
			saveSettings();
		});
	}

	QAction *hover = m->addAction("Reveal when mouse hits the edge");
	hover->setCheckable(true);
	hover->setChecked(hoverReveal_);
	connect(hover, &QAction::toggled, this, [this](bool on) {
		hoverReveal_ = on;
		saveSettings();
	});

	m->addSeparator();
	auto *docks = m->addMenu("Docks");
	for (auto *d : host_->findChildren<QDockWidget *>())
		docks->addAction(d->toggleViewAction());

	return m;
}

void OverlayPanel::openObsSettings()
{
	auto *mw = static_cast<QMainWindow *>(obs_frontend_get_main_window());
	if (!mw)
		return;
	if (auto *a = mw->findChild<QAction *>("actionSettings"))
		a->trigger();
	else if (auto *b = mw->findChild<QPushButton *>("settingsButton"))
		b->click();
}

QRect OverlayPanel::targetRect(bool shown) const
{
	const QRect full = screen_->geometry();
	const QRect avail = screen_->availableGeometry(); // keeps clear of the taskbar vertically
	const int w = width_;
	int x;
	if (edge_ == Edge::Left)
		x = shown ? full.left() : full.left() - w;
	else
		x = shown ? full.right() - w + 1 : full.right() + 1;
	return QRect(x, avail.top(), w, avail.height());
}

void OverlayPanel::applyGeometryIfShown()
{
	if (shown_ && isVisible())
		setGeometry(targetRect(true));
}

void OverlayPanel::toggle()
{
	if (shown_)
		slideOut();
	else
		slideIn(false);
}

void OverlayPanel::slideIn(bool byHover)
{
	if (shown_)
		return;
	shown_ = true;
	openedByHover_ = byHover;
	leaveTicks_ = 0;

	screen_ = QGuiApplication::screenAt(QCursor::pos());
	if (!screen_)
		screen_ = QGuiApplication::primaryScreen();

	const QRect shownRect = targetRect(true);
	if (!isVisible()) {
		setGeometry(targetRect(false));
		show();
	} else {
		resize(shownRect.size());
	}
	raise();

	anim_->stop();
	anim_->setStartValue(pos());
	anim_->setEndValue(shownRect.topLeft());
	anim_->start();
}

void OverlayPanel::slideOut()
{
	if (!shown_)
		return;
	shown_ = false;
	saveSettings();

	anim_->stop();
	anim_->setStartValue(pos());
	anim_->setEndValue(targetRect(false).topLeft());
	anim_->start();
}

void OverlayPanel::pollCursor()
{
	const QPoint c = QCursor::pos();

	if (!shown_) {
		if (!hoverReveal_) {
			edgeTicks_ = 0;
			return;
		}
		QScreen *s = QGuiApplication::screenAt(c);
		if (!s) {
			edgeTicks_ = 0;
			return;
		}
		const QRect g = s->geometry();
		const bool atEdge = (edge_ == Edge::Left) ? c.x() <= g.left() : c.x() >= g.right();
		edgeTicks_ = atEdge ? edgeTicks_ + 1 : 0;
		if (edgeTicks_ >= 6) { // ~0.35 s dwell so passing the cursor by doesn't trigger it
			edgeTicks_ = 0;
			slideIn(true);
		}
	} else if (openedByHover_ && !pinned_) {
		leaveTicks_ = frameGeometry().contains(c) ? 0 : leaveTicks_ + 1;
		if (leaveTicks_ >= 10)
			slideOut();
	}
}

void OverlayPanel::paintEvent(QPaintEvent *)
{
	QPainter p(this);
	p.setPen(palette().mid().color());
	p.drawRect(rect().adjusted(0, 0, -1, -1));
}

void OverlayPanel::loadSettings()
{
	QSettings s = openSettings();
	edge_ = s.value("edge", "left").toString() == "right" ? Edge::Right : Edge::Left;
	width_ = qBound(280, s.value("width", 380).toInt(), 700);
	opacity_ = qBound(0.3, s.value("opacity", 1.0).toDouble(), 1.0);
	pinned_ = s.value("pinned", false).toBool();
	hoverReveal_ = s.value("hoverReveal", false).toBool();
}

void OverlayPanel::saveSettings()
{
	QSettings s = openSettings();
	s.setValue("edge", edge_ == Edge::Right ? "right" : "left");
	s.setValue("width", width_);
	s.setValue("opacity", opacity_);
	s.setValue("pinned", pinned_);
	s.setValue("hoverReveal", hoverReveal_);
	if (host_)
		s.setValue("dockState", host_->saveState());
}
