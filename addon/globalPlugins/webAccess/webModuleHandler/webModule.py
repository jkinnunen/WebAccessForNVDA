# globalPlugins/webAccess/webModuleHandler/webModule.py
# -*- coding: utf-8 -*-

# This file is part of Web Access for NVDA.
# Copyright (C) 2015-2019 Accessolutions (http://accessolutions.fr)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# See the file COPYING.txt at the root of this distribution for more details.


__version__ = "2019.01.03"

__author__ = (
	"Yannick Plassiard <yan@mistigri.org>, "
	"Frédéric Brugnot <f.brugnot@accessolutions.fr>, "
	"Julien Cochuyt <j.cochuyt@accessolutions.fr>"
	)


import os

import addonHandler
addonHandler.initTranslation()
import api
import baseObject
import braille
import controlTypes
from logHandler import log
import scriptHandler
import speech
import ui

from .. import json
from ..packaging import version
from .. import presenter
from .. import ruleHandler
from ..ruleHandler import ruleTypes
from ..webAppLib import *


class WebModule(baseObject.ScriptableObject):
	
	FORMAT_VERSION_STR = "0.4-dev"
	FORMAT_VERSION = version.parse(FORMAT_VERSION_STR)
	
	url = None
	name = None
	windowTitle = None
	markerManager = None
	widgetManager = None
	activeWidget = None
	presenter = None

	def __init__(self, data=None):
		super(WebModule, self).__init__()
		self.activePageTitle = None
		self.activePageIdentifier = None
		from .. import widgets
		self.widgetManager = widgets.WidgetManager(self)
		self.activeWidget = None
		self.presenter = presenter.Presenter(self)
		self.markerManager = ruleHandler.MarkerManager(self)

		self.load(data)
		if self.name is None:
			log.error(u"No web module defined in the configuration data: %s" % data)
			raise Exception("No web module defined in the configuration data.")
	
	def __str__(self):
		return u"WebModule {name}".format(
			name=self.name if self.name is not None else "<noName>"
			)

	def dump(self):
		data = {"formatVersion": self.FORMAT_VERSION_STR}
		
		data["WebModule"] = {
			"name": self.name,
			"url": self.url,
			"windowTitle": self.windowTitle,
		}
		
		if self.markerManager is None:
			# Do not risk to erase an existing data file while in an
			# unstable state.
			raise Exception(
				"WebModule has no marker manager: {name}"
				"".format(name=self.name)
			)
		else:
			queriesData = self.markerManager.getQueriesData()
			if len(queriesData) > 0:
				data["Rules"] = queriesData
			else:
				data["Rules"] = []
		return data
	
	def load(self, data):
		if data is None:
			log.info(u"%s: No data to load" % self.name)
			return True
		
		formatVersion = data.get("formatVersion")
		# Ensure compatibility with data files prior to format versioning
		if formatVersion is None:
			formatVersion = ""
			# Back to the "WebAppHandler" days
			if "WebModule" not in data and "WebApp" in data:
				data["WebModule"] = data.pop("WebApp")
			if "Rules" not in data and "PlaceMarkers" in data:
				data["Rules"] = data.pop("PlaceMarkers")
			# Earlier versions supported only a single URL trigger
			url = data.get("WebModule", {}).get("url", None)
			if isinstance(url, basestring):
				data["WebModule"]["url"] = [url]
			# Custom labels for certain fields are not supported anymore
			# TODO: Re-implement custom field labels?
			if "FieldLabels" in data:
				log.warning("FieldLabels not supported")
		formatVersion = version.parse(formatVersion)
		if formatVersion < version.parse("0.2"):
			for rule in data.get("Rules", []):
				if "context" in rule:
					rule["requiresContext"] = rule.pop("context")
				if "isContext" in rule:
					if rule.get("isContext"):
						rule["definesContext"] = "pageId"
					del rule["isContext"]
		if formatVersion < version.parse("0.3"):
			for rule in data.get("Rules", []):
				if rule.get("autoAction") == "noAction":
					del rule["autoAction"]
		if formatVersion < version.parse("0.4"):
			for rule in data.get("Rules", []):
				rule.setdefault("type", ruleTypes.MARKER)
				for reason in ("isPageTitle", "definesContext"):
					if not rule.get(reason):
						continue
					notSupported = []
					for key in (
						"gestures", "autoAction",
						"multiple", "formMode", "sayName"
					):
						if rule.get(key):
							notSupported.append(key)
					if notSupported:
						log.error(
							u"Web module \"{module}\" - rule \"{rule}\": "
							u"Not supported on rules with property "
							u"\"{reason}\": {notSupported}".format(
								module=data.get("WebModule", {}).get("name"),
								rule=rule.get("name"),
								reason=reason,
								notSupported=u", ".join(notSupported)
							)
						)
					elif rule.get("isPageTitle"):
						rule["type"] = ruleTypes.PAGE_TITLE_1
					elif rule["definesContext"] in ("pageId", "pageType"):
						rule["type"] = ruleTypes.PAGE_TYPE
					else:
						rule["type"] = ruleTypes.PARENT
				if rule.get("requiresContext"):
					rule["contextParent"] = rule["requiresContext"]
					log.error(
						u"Web module \"{module}\" - rule \"{rule}\": "
						u"Property \"requiresContext\" has been copied to " 
						u"\"contextParent\", which is probably not accurate. "
						u"Please redefine the required context.".format(
							module=data.get("WebModule", {}).get("name"),
							rule=rule.get("name")
						)
					)
				for key in (
					"definesContext",
					"requiresContext",
					"isPageTitle"
				):
					try:
						del rule[key]
					except KeyError:
						pass
				# If it is upper-case (as in non-normalized identifiers),
				# `keyboardHandler.KeyboardInputGesture.getDisplayTextForIdentifier`
				# does not properly handle the NVDA key. 
				gestures = rule.get("gestures", {})
				# Get ready for Python 3: dict.items will return an iterator.
				for key, value in list(gestures.items()):
					if "NVDA" not in key:
						continue
					del gestures[key]
					key = key.replace("NVDA", "nvda")
					gestures[key] = value				
		
		if formatVersion > self.FORMAT_VERSION:
			raise version.InvalidVersion(
				"WebModule format version not supported: {ver}".format(
					ver=formatVersion
				)
			)
		item = data.get("WebModule")
		if item is not None:
			if "name" in item:
				self.name = item["name"]
			else:
				log.warning("WebModule has no name")
			if "url" in item:
				url = item["url"]
				if not isinstance(url, list):
					log.warning(
						"Unexpected WebModule/url: "
						"{url}".format(url)
						)
				else:
					self.url = url
			if "windowTitle" in item:
				self.windowTitle = item["windowTitle"]
		del item
		items = data.get("Rules")
		if items is not None:
			self.markerManager.setQueriesData(items)
		del items
		return True
	
	_cache_pageTitle = False
	
	def _get_pageTitle(self):
		title = self.activePageTitle
		if not title:
			try:
				title = self.markerManager.getPageTitle()
			except:
				log.exception(
					u'Error while retrieving page title'
					u' in WebModule "{}"'.format(
						self.name
					)
				)
		if not title:
			title = api.getForegroundObject().name
		return title

	def getPresentationConfig(self):
		return {
			'braille.stripBlanks': True,
			}
	
	def event_webApp_init(self, obj, nextHandler):
		self.loadUserFile()
		nextHandler()

	def event_webApp_pageChanged(self, pageTitle, nextHandler):
		speech.cancelSpeech()
		playWebAppSound("pageChanged")
		speech.speakMessage(pageTitle)
	
	def event_webApp_gainFocus(self, obj, nextHandler):
		if obj.role not in [controlTypes.ROLE_DOCUMENT, controlTypes.ROLE_FRAME, controlTypes.ROLE_INTERNALFRAME]:
			nextHandler()

	def event_focusEntered(self, obj, nextHandler):
		if obj.role != controlTypes.ROLE_DOCUMENT:
			nextHandler()

	def event_gainFocus(self, obj, nextHandler):
		nextHandler()

	def event_webApp_loseFocus(self, obj, nextHandler):
		playWebAppSound("webAppLoseFocus")
		nextHandler()
		
	def claimForJABObject(self, obj):
		return False

	def script_title(self, gesture):
		title = self.pageTitle
		repeatCount = scriptHandler.getLastScriptRepeatCount()
		if repeatCount == 0:
			ui.message(title)
		elif repeatCount == 1:
			speech.speakSpelling(title)
		else:
			if api.copyToClip(title):
				ui.message(_("%s copied to clipboard") % title)

	def script_sayWebAppName(self, gesture):
		# Translators: Speak name of current web module
		ui.message(_(u"Current web module is: {name}").format(name=self.name))

	__gestures = {
		"kb:nvda+t": "title",
		"kb:nvda+shift+t": "sayWebAppName",
	}
	