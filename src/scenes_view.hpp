#pragma once

#include <QWidget>

class QListWidget;

// Port of the "Production > Scene switching" feature.
class ScenesView : public QWidget {
	Q_OBJECT
public:
	explicit ScenesView(QWidget *parent = nullptr);

private slots:
	void refresh();

private:
	QListWidget *list_;
};
