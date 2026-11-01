#pragma once

#include <QWidget>

class QMainWindow;
class QMenu;
class QPropertyAnimation;
class QScreen;
class QTimer;
class QToolButton;

// Frameless, always-on-top panel that slides in from a screen edge.
// Content is a set of QDockWidgets (modular: drag, tab, stack, hide).
class OverlayPanel : public QWidget {
	Q_OBJECT
public:
	enum class Edge { Left, Right };

	explicit OverlayPanel(QWidget *parent = nullptr);
	~OverlayPanel() override;

public slots:
	void toggle();
	void slideIn(bool byHover = false);
	void slideOut();

protected:
	void paintEvent(QPaintEvent *) override;

private:
	void buildUi();
	QMenu *buildMenu();
	QRect targetRect(bool shown) const;
	void pollCursor();
	void applyGeometryIfShown();
	void loadSettings();
	void saveSettings();
	static void openObsSettings();

	QMainWindow *host_ = nullptr;
	QToolButton *pinBtn_ = nullptr;
	QPropertyAnimation *anim_ = nullptr;
	QTimer *poll_ = nullptr;
	QScreen *screen_ = nullptr;

	Edge edge_ = Edge::Left;
	int width_ = 380;
	qreal opacity_ = 1.0;
	bool pinned_ = false;
	bool hoverReveal_ = false;

	bool shown_ = false;
	bool openedByHover_ = false;
	int edgeTicks_ = 0;
	int leaveTicks_ = 0;
};
