#include "scenes_view.hpp"
#include "obs_events.hpp"

#include <obs-frontend-api.h>

#include <QListWidget>
#include <QVBoxLayout>
#include <cstring>

ScenesView::ScenesView(QWidget *parent) : QWidget(parent)
{
	auto *lay = new QVBoxLayout(this);
	lay->setContentsMargins(6, 6, 6, 6);

	list_ = new QListWidget(this);
	lay->addWidget(list_);

	// itemClicked (not currentRowChanged) so refresh() can't feed back into OBS.
	connect(list_, &QListWidget::itemClicked, this, [](QListWidgetItem *it) {
		obs_source_t *s = obs_get_source_by_name(it->text().toUtf8().constData());
		if (s) {
			obs_frontend_set_current_scene(s);
			obs_source_release(s);
		}
	});

	connect(&ObsEvents::instance(), &ObsEvents::scenesChanged, this, &ScenesView::refresh);
	refresh();
}

void ScenesView::refresh()
{
	obs_frontend_source_list scenes = {};
	obs_frontend_get_scenes(&scenes);
	obs_source_t *cur = obs_frontend_get_current_scene();
	const char *curName = cur ? obs_source_get_name(cur) : nullptr;

	list_->clear();
	for (size_t i = 0; i < scenes.sources.num; i++) {
		const char *name = obs_source_get_name(scenes.sources.array[i]);
		auto *item = new QListWidgetItem(QString::fromUtf8(name), list_);
		if (curName && std::strcmp(curName, name) == 0)
			list_->setCurrentItem(item);
	}

	obs_source_release(cur);
	obs_frontend_source_list_free(&scenes);
}
