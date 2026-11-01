#pragma once

#include <QHash>
#include <QImage>
#include <QStringList>
#include <QTimer>
#include <QWidget>

class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QListWidgetItem;

// Port of the Gallery: recordings, replays, screenshots, favorites, search,
// lazy thumbnails and file actions. Reads the folder OBS records into.
class GalleryView : public QWidget {
	Q_OBJECT
public:
	explicit GalleryView(QWidget *parent = nullptr);

protected:
	void showEvent(QShowEvent *) override;

private slots:
	void rescan();
	void applyFilter();
	void showContextMenu(const QPoint &pos);

private:
	enum class Kind { Recording, Replay, Screenshot };

	static Kind kindOf(const QString &path);
	QString folder() const;
	bool isFavorite(const QString &path) const;
	void setFavorite(const QString &path, bool on);
	void refreshItemText(QListWidgetItem *item);
	void setThumbnail(const QString &path, const QImage &img);

	void openFile(const QString &path);
	void showInFolder(const QString &path);
	void renameFile(QListWidgetItem *item);
	void deleteFile(QListWidgetItem *item);

	QListWidget *list_;
	QComboBox *category_;
	QLineEdit *search_;
	QLabel *pathLabel_;
	QTimer debounce_;
	QHash<QString, QListWidgetItem *> items_;
	QStringList favorites_;
	bool dirty_ = true;
};
