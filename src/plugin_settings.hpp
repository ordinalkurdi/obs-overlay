#pragma once

#include <obs-module.h>

#include <QDir>
#include <QSettings>
#include <QString>

// One ini file in OBS's per-plugin config folder, shared by the panel and the views.
inline QSettings openSettings()
{
	char *dir = obs_module_config_path("");
	const QString d = QString::fromUtf8(dir ? dir : "");
	bfree(dir);
	QDir().mkpath(d);
	return QSettings(QDir(d).filePath("settings.ini"), QSettings::IniFormat);
}
