#include "gallery_view.hpp"
#include "obs_events.hpp"
#include "plugin_settings.hpp"

#include <obs-frontend-api.h>

#include <QApplication>
#include <QClipboard>
#include <QComboBox>
#include <QDesktopServices>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QImageReader>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMessageBox>
#include <QPixmap>
#include <QPointer>
#include <QProcess>
#include <QStandardPaths>
#include <QThreadPool>
#include <QUrl>
#include <QVBoxLayout>
#include <algorithm>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <shobjidl.h>
#include <string>
#endif

static const QSize kThumb(160, 90);
static const QStringList kVideoExt = {"mkv", "mp4", "mov", "flv", "ts", "m4v", "webm"};
static const QStringList kImageExt = {"png", "jpg", "jpeg", "bmp", "webp"};
static constexpr int kMaxItems = 200;

#ifdef _WIN32
static QImage hbitmapToImage(HBITMAP hbm)
{
	BITMAP bm{};
	if (!GetObject(hbm, sizeof(bm), &bm) || bm.bmWidth <= 0 || bm.bmHeight <= 0)
		return {};
	BITMAPINFO bi{};
	bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
	bi.bmiHeader.biWidth = bm.bmWidth;
	bi.bmiHeader.biHeight = -bm.bmHeight; // top-down
	bi.bmiHeader.biPlanes = 1;
	bi.bmiHeader.biBitCount = 32;
	bi.bmiHeader.biCompression = BI_RGB;
	QImage img(bm.bmWidth, bm.bmHeight, QImage::Format_RGB32); // ignore alpha: shell thumbs are opaque
	HDC dc = GetDC(nullptr);
	const int ok = GetDIBits(dc, hbm, 0, bm.bmHeight, img.bits(), &bi, DIB_RGB_COLORS);
	ReleaseDC(nullptr, dc);
	return ok ? img : QImage();
}
#endif

// Video thumbnails come from the Windows shell, so no Qt Multimedia / ffmpeg dependency.
static QImage videoThumb(const QString &path)
{
#ifdef _WIN32
	const HRESULT hrInit = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
	QImage out;
	const std::wstring wp = QDir::toNativeSeparators(path).toStdWString();
	IShellItemImageFactory *factory = nullptr;
	if (SUCCEEDED(SHCreateItemFromParsingName(wp.c_str(), nullptr, IID_PPV_ARGS(&factory))) && factory) {
		HBITMAP hbm = nullptr;
		const SIZE sz{kThumb.width() * 2, kThumb.height() * 2};
		if (SUCCEEDED(factory->GetImage(sz, SIIGBF_BIGGERSIZEOK, &hbm)) && hbm) {
			out = hbitmapToImage(hbm);
			DeleteObject(hbm);
		}
		factory->Release();
	}
	if (SUCCEEDED(hrInit))
		CoUninitialize();
	return out;
#else
	Q_UNUSED(path);
	return {};
#endif
}

static QImage imageThumb(const QString &path)
{
	QImageReader r(path);
	r.setAutoTransform(true);
	const QSize s = r.size();
	if (s.isValid())
		r.setScaledSize(s.scaled(kThumb * 2, Qt::KeepAspectRatio));
	return r.read();
}

GalleryView::GalleryView(QWidget *parent) : QWidget(parent)
{
	favorites_ = openSettings().value("gallery/favorites").toStringList();

	auto *lay = new QVBoxLayout(this);
	lay->setContentsMargins(6, 6, 6, 6);
	lay->setSpacing(4);

	auto *top = new QHBoxLayout;
	search_ = new QLineEdit(this);
	search_->setPlaceholderText("Search...");
	search_->setClearButtonEnabled(true);
	category_ = new QComboBox(this);
	category_->addItems({"All", "Recordings", "Replays", "Screenshots", "Favorites"});
	top->addWidget(search_, 1);
	top->addWidget(category_);
	lay->addLayout(top);

	list_ = new QListWidget(this);
	list_->setViewMode(QListView::IconMode);
	list_->setIconSize(kThumb);
	list_->setGridSize(QSize(kThumb.width() + 16, kThumb.height() + 36));
	list_->setResizeMode(QListView::Adjust);
	list_->setMovement(QListView::Static);
	list_->setWordWrap(true);
	list_->setUniformItemSizes(true);
	list_->setContextMenuPolicy(Qt::CustomContextMenu);
	lay->addWidget(list_, 1);

	pathLabel_ = new QLabel(this);
	pathLabel_->setStyleSheet("color: gray; font-size: 10px;");
	pathLabel_->setTextInteractionFlags(Qt::TextSelectableByMouse);
	lay->addWidget(pathLabel_);

	connect(search_, &QLineEdit::textChanged, this, &GalleryView::applyFilter);
	connect(category_, &QComboBox::currentIndexChanged, this, &GalleryView::applyFilter);
	connect(list_, &QListWidget::customContextMenuRequested, this, &GalleryView::showContextMenu);
	connect(list_, &QListWidget::itemDoubleClicked, this,
		[this](QListWidgetItem *it) { openFile(it->data(Qt::UserRole).toString()); });

	// Refresh shortly after OBS finishes writing a recording / replay / screenshot.
	debounce_.setSingleShot(true);
	debounce_.setInterval(1500);
	connect(&debounce_, &QTimer::timeout, this, [this] {
		dirty_ = true;
		if (isVisible())
			rescan();
	});
	connect(&ObsEvents::instance(), &ObsEvents::stateChanged, this, [this] { debounce_.start(); });
}

void GalleryView::showEvent(QShowEvent *e)
{
	QWidget::showEvent(e);
	if (dirty_)
		rescan();
}

QString GalleryView::folder() const
{
	char *p = obs_frontend_get_current_record_output_path();
	QString dir = QString::fromUtf8(p ? p : "");
	bfree(p);
	if (dir.isEmpty())
		dir = QStandardPaths::writableLocation(QStandardPaths::MoviesLocation);
	return dir;
}

GalleryView::Kind GalleryView::kindOf(const QString &path)
{
	const QFileInfo fi(path);
	if (kImageExt.contains(fi.suffix().toLower()))
		return Kind::Screenshot;
	if (fi.completeBaseName().startsWith("Replay", Qt::CaseInsensitive))
		return Kind::Replay;
	return Kind::Recording;
}

bool GalleryView::isFavorite(const QString &path) const
{
	return favorites_.contains(path);
}

void GalleryView::setFavorite(const QString &path, bool on)
{
	if (on && !favorites_.contains(path))
		favorites_ << path;
	else if (!on)
		favorites_.removeAll(path);
	openSettings().setValue("gallery/favorites", favorites_);
	if (auto *it = items_.value(path, nullptr))
		refreshItemText(it);
	applyFilter();
}

void GalleryView::refreshItemText(QListWidgetItem *item)
{
	const QString path = item->data(Qt::UserRole).toString();
	item->setText((isFavorite(path) ? QString::fromUtf8("\u2605 ") : QString()) +
		      QFileInfo(path).completeBaseName());
}

void GalleryView::rescan()
{
	dirty_ = false;
	list_->clear();
	items_.clear();

	const QString dir = folder();
	pathLabel_->setText(dir);

	QStringList filters;
	for (const QString &e : kVideoExt + kImageExt)
		filters << "*." + e;

	QFileInfoList files;
	QDirIterator it(dir, filters, QDir::Files);
	while (it.hasNext()) {
		it.next();
		files << it.fileInfo();
	}
	std::sort(files.begin(), files.end(),
		  [](const QFileInfo &a, const QFileInfo &b) { return a.lastModified() > b.lastModified(); });
	if (files.size() > kMaxItems)
		files.resize(kMaxItems);

	QPixmap placeholder(kThumb);
	placeholder.fill(QColor(60, 60, 60));

	QPointer<GalleryView> self(this);
	for (const QFileInfo &fi : files) {
		const QString path = fi.absoluteFilePath();
		auto *item = new QListWidgetItem(QIcon(placeholder), QString(), list_);
		item->setData(Qt::UserRole, path);
		item->setToolTip(QString("%1\n%2 MB  -  %3")
					 .arg(QDir::toNativeSeparators(path))
					 .arg(fi.size() / 1048576.0, 0, 'f', 1)
					 .arg(fi.lastModified().toString("yyyy-MM-dd HH:mm")));
		refreshItemText(item);
		items_.insert(path, item);

		const Kind k = kindOf(path);
		QThreadPool::globalInstance()->start([self, path, k] {
			const QImage img = (k == Kind::Screenshot) ? imageThumb(path) : videoThumb(path);
			if (img.isNull())
				return;
			QMetaObject::invokeMethod(
				qApp, [self, path, img] {
					if (self)
						self->setThumbnail(path, img);
				},
				Qt::QueuedConnection);
		});
	}
	applyFilter();
}

void GalleryView::setThumbnail(const QString &path, const QImage &img)
{
	if (auto *item = items_.value(path, nullptr))
		item->setIcon(QIcon(QPixmap::fromImage(img.scaled(kThumb, Qt::KeepAspectRatio, Qt::SmoothTransformation))));
}

void GalleryView::applyFilter()
{
	const QString q = search_->text().trimmed();
	const int cat = category_->currentIndex();
	for (int i = 0; i < list_->count(); i++) {
		QListWidgetItem *it = list_->item(i);
		const QString path = it->data(Qt::UserRole).toString();
		const Kind k = kindOf(path);
		bool ok = true;
		switch (cat) {
		case 1: ok = (k == Kind::Recording); break;
		case 2: ok = (k == Kind::Replay); break;
		case 3: ok = (k == Kind::Screenshot); break;
		case 4: ok = isFavorite(path); break;
		default: break;
		}
		if (ok && !q.isEmpty())
			ok = QFileInfo(path).fileName().contains(q, Qt::CaseInsensitive);
		it->setHidden(!ok);
	}
}

void GalleryView::showContextMenu(const QPoint &pos)
{
	QListWidgetItem *item = list_->itemAt(pos);
	if (!item)
		return;
	const QString path = item->data(Qt::UserRole).toString();

	QMenu m(this);
	m.addAction("Open", this, [this, path] { openFile(path); });
	m.addAction("Show in folder", this, [this, path] { showInFolder(path); });
	m.addAction("Copy path", this,
		    [path] { QApplication::clipboard()->setText(QDir::toNativeSeparators(path)); });
	m.addSeparator();
	const bool fav = isFavorite(path);
	m.addAction(fav ? "Remove from favorites" : "Add to favorites", this,
		    [this, path, fav] { setFavorite(path, !fav); });
	m.addAction("Rename...", this, [this, item] { renameFile(item); });
	m.addAction("Delete (Recycle Bin)", this, [this, item] { deleteFile(item); });
	m.exec(list_->viewport()->mapToGlobal(pos));
}

void GalleryView::openFile(const QString &path)
{
	QDesktopServices::openUrl(QUrl::fromLocalFile(path));
}

void GalleryView::showInFolder(const QString &path)
{
#ifdef _WIN32
	QProcess::startDetached("explorer.exe", {"/select," + QDir::toNativeSeparators(path)});
#else
	QDesktopServices::openUrl(QUrl::fromLocalFile(QFileInfo(path).absolutePath()));
#endif
}

void GalleryView::renameFile(QListWidgetItem *item)
{
	const QString path = item->data(Qt::UserRole).toString();
	const QFileInfo fi(path);
	bool ok = false;
	const QString name = QInputDialog::getText(this, "Rename", "New name:", QLineEdit::Normal,
						   fi.completeBaseName(), &ok)
				     .trimmed();
	if (!ok || name.isEmpty() || name == fi.completeBaseName())
		return;

	const QString target = fi.absoluteDir().filePath(name + "." + fi.suffix());
	if (QFile::exists(target) || !QFile::rename(path, target)) {
		QMessageBox::warning(this, "Rename", "Could not rename the file.");
		return;
	}
	const bool wasFav = isFavorite(path);
	if (wasFav)
		setFavorite(path, false);
	items_.remove(path);
	item->setData(Qt::UserRole, target);
	items_.insert(target, item);
	if (wasFav)
		setFavorite(target, true);
	refreshItemText(item);
}

void GalleryView::deleteFile(QListWidgetItem *item)
{
	const QString path = item->data(Qt::UserRole).toString();
	if (QMessageBox::question(this, "Delete",
				  QString("Move \"%1\" to the Recycle Bin?").arg(QFileInfo(path).fileName())) !=
	    QMessageBox::Yes)
		return;
	if (!QFile::moveToTrash(path)) {
		QMessageBox::warning(this, "Delete", "Could not move the file to the Recycle Bin.");
		return;
	}
	setFavorite(path, false);
	items_.remove(path);
	delete list_->takeItem(list_->row(item));
}
