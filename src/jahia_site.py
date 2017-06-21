"""(c) All rights reserved. ECOLE POLYTECHNIQUE FEDERALE DE LAUSANNE, Switzerland, VPSI, 2017"""

import os
import logging

from bs4 import BeautifulSoup
from box import Box
from file import File
from link import Link
from page import Page
from page_content import PageContent
from utils import Utils

"""
This file is named jahia_site to avoid a conflict with Site [https://docs.python.org/3/library/site.html]
"""


class Site:
    """A Jahia Site. Have 1 to N Pages"""

    def __init__(self, base_path, name, root_path=""):
        self.base_path = base_path
        self.name = name
        # the server name, e.g. "master.epfl.ch"
        self.server_name = ""
        # the root_path, by default it's empty
        # FIXME: would be better in exporter, or set by exporter
        self.root_path = root_path

        # parse the properties at the beginning, we need the
        # server_name for later
        self.parse_properties()

        # the export files containing the pages data.
        # the dict key is the language code (e.g. "en") and
        # the dict value is the file absolute path
        self.export_files = {}

        # the site languages
        self.languages = []

        for file in os.listdir(base_path):
            if file.startswith("export_"):
                language = file[7:9]
                path = base_path + "/" + file
                self.export_files[language] = path
                self.languages.append(language)

        # site params that are parsed later. There are dicts because
        # we have a value for each language. The dict key is the language,
        # and the dict value is the specific value
        self.title = {}
        self.acronym = {}
        self.theme = {}
        self.css_url = {}

        # breadcrumb
        self.breadcrumb_title = {}
        self.breadcrumb_url = {}

        # footer
        self.footer = {}

        # the pages
        self.pages_by_pid = {}
        self.pages_by_uuid = {}

        # variables for the report
        self.num_files = 0
        self.num_pages = 0
        self.internal_links = 0
        self.absolute_links = 0
        self.external_links = 0
        self.file_links = 0
        self.data_links = 0
        self.mailto_links = 0
        self.unknown_links = 0
        self.num_boxes = {}
        self.report = ""

        # set for convenience, to avoid:
        #   [p for p in self.pages if p.is_homepage()][0]
        self.homepage = None

        # the files
        self.files = []

        # parse the data
        self.parse_data()

        # generate the report
        self.generate_report()

    def full_path(self, path):
        """
        Return the page full, adding the site root_path at the beginning
        """
        return self.root_path + path

    def parse_properties(self):
        """
        Parse the properties found in site.properties
        """

        properties = {}

        with open(self.base_path + "/site.properties") as file:
            lines = file.readlines()

            for line in lines:
                if "=" not in line:
                    continue

                values = line.split("=")

                properties[values[0].strip()] = values[1].strip()

        self.server_name = properties["siteservername"]

    def parse_data(self):
        """Parse the Site data"""

        # do the parsing
        self.parse_site_params()
        self.parse_breadcrumb()
        self.parse_footer()
        self.parse_pages()
        self.parse_pages_content()
        self.parse_files()
        self.fix_links()

    def parse_site_params(self,):
        """Parse the site params"""
        for language, dom_path in self.export_files.items():
            dom = Utils.get_dom(dom_path)

            self.title[language] = Utils.get_tag_attribute(dom, "siteName", "jahia:value")
            self.theme[language] = Utils.get_tag_attribute(dom, "theme", "jahia:value")
            self.acronym[language] = Utils.get_tag_attribute(dom, "acronym", "jahia:value")
            self.css_url[language] = "//static.epfl.ch/v0.23.0/styles/%s-built.css" % self.theme

    def parse_footer(self):
        """parse site footer"""

        for language, dom_path in self.export_files.items():
            dom = Utils.get_dom(dom_path)

            # is positioned on children of main jahia:page element
            elements = dom.firstChild.childNodes

            self.footer[language] = []

            for child in elements:
                if child.ELEMENT_NODE != child.nodeType:
                    continue

                if "bottomLinksListList" == child.nodeName:

                    nb_items_in_footer = len(child.getElementsByTagName("jahia:url"))

                    if nb_items_in_footer == 0:
                        """ This page has probably the default footer """
                        break

                    elif nb_items_in_footer > 0:

                        elements = child.getElementsByTagName("jahia:url")
                        for element in elements:
                            link = Link(
                                url=element.getAttribute('jahia:value'),
                                title=element.getAttribute('jahia:title')
                            )
                            self.footer[language].append(link)
                        break

    def parse_breadcrumb(self):
        """Parse the breadcrumb"""

        for language, dom_path in self.export_files.items():
            dom = Utils.get_dom(dom_path)

            breadcrumb_links = dom.getElementsByTagName("breadCrumbLink")
            nb_found = len(breadcrumb_links)
            if nb_found !=1:
                logging.warning("Found %s breadcrumb link(s) instead of 1", nb_found)
                if nb_found == 0:
                    continue
            breadcrumb_link = breadcrumb_links[0]

            for child in breadcrumb_link.childNodes:
                if child.ELEMENT_NODE != child.nodeType:
                    continue

                if 'jahia:url' == child.nodeName:
                    self.breadcrumb_url[language] = child.getAttribute('jahia:value')
                    self.breadcrumb_title[language] = child.getAttribute('jahia:title')
                    break

    def parse_pages(self):
        """
        Parse the Pages. Here we parse only the common data between
        multilingual pages
        """

        # we check each export files because a Page could be defined
        # in one language but not in another
        for language, dom_path in self.export_files.items():
            dom = Utils.get_dom(dom_path)

            xml_pages = dom.getElementsByTagName("jahia:page")

            for xml_page in xml_pages:
                pid = xml_page.getAttribute("jahia:pid")
                template = xml_page.getAttribute("jahia:template")

                # we don't parse the sitemap as it's not a real page
                if template == "sitemap":
                    continue

                # check if we already parsed this page
                if pid in self.pages_by_pid:
                    continue

                page = Page(self, xml_page)

                # flag the homepage for convenience
                if page.is_homepage():
                    self.homepage = page

                # add the Page to the cache
                self.pages_by_pid[page.pid] = page
                self.pages_by_uuid[page.uuid] = page

    def parse_pages_content(self):
        """
        Parse the PageContent. This is the content that is specific
        for each language.
        """

        for language, dom_path in self.export_files.items():
            dom = Utils.get_dom(dom_path)

            xml_pages = dom.getElementsByTagName("jahia:page")

            for xml_page in xml_pages:
                pid = xml_page.getAttribute("jahia:pid")
                template = xml_page.getAttribute("jahia:template")

                # we don't parse the sitemap as it's not a real page
                if template == "sitemap":
                    continue

                # retrieve the Page definition that we already parsed
                page = self.pages_by_pid[pid]
                page_content = PageContent(page, language, xml_page)

                # main tag is the parent of all boxes types
                main_elements = xml_page.getElementsByTagName("main")

                boxes = []

                for main_element in main_elements:
                    # check if the box belongs to the current page
                    if not self.belongs_to(main_element, page):
                        continue

                    type = main_element.getAttribute("jcr:primaryType")

                    # the "epfl:faqBox" element contains one or more "epfl:faqList"
                    if "epfl:faqBox" == type:
                        faq_list_elements = main_element.getElementsByTagName("faqList")

                        for faq_list_element in faq_list_elements:
                            box = Box(site=self, page_content=page_content, element=faq_list_element)
                            boxes.append(box)

                    else:
                        # TODO remove the multibox parameter and check for combo boxes instead
                        # Check if xml_box contains many boxes
                        multibox = main_element.getElementsByTagName("text").length > 1
                        box = Box(site=self, page_content=page_content, element=main_element, multibox=multibox)
                        boxes.append(box)

                page_content.boxes = boxes
                page.contents[language] = page_content

    def parse_files(self):
        """Parse the files"""
        start = "%s/content/sites/%s/files" % (self.base_path, self.name)

        for (path, dirs, files) in os.walk(start):
            for file_name in files:
                # we exclude the thumbnails
                if file_name in ["thumbnail", "thumbnail2"]:
                    continue

                self.files.append(File(name=file_name, path=path))

    def get_all_boxes(self):
        """
        Returns all the Site boxes.
        """
        boxes = []

        for page in self.pages_by_pid.values():
            for page_content in page.contents.values():
                # boxes in the content
                for box in page_content.boxes:
                    boxes.append(box)
                # boxes in the sidebar
                for box in page_content.sidebar.boxes:
                    boxes.append(box)

        return boxes

    def belongs_to(self, element, page):
        """Check if the given element belongs to the given page"""
        parent = element.parentNode

        while "jahia:page" != parent.nodeName:
            parent = parent.parentNode

        return page.pid == parent.getAttribute("jahia:pid")

    def fix_links(self):
        """
        Fix all the boxes links. This must be done at the end,
        when all the pages have been parsed.
        """
        for box in self.get_all_boxes():
            soup = BeautifulSoup(box.content, 'html.parser')

            self.fix_links_in_tag(box=box, soup=soup, tag_name="a", attribute="href")
            self.fix_links_in_tag(box=box, soup=soup, tag_name="img", attribute="src")
            self.fix_links_in_tag(box=box, soup=soup, tag_name="script", attribute="src")

    def fix_links_in_tag(self, box, soup, tag_name, attribute):
        """
        Fix the links in the given type of tag
        """
        tags = soup.find_all(tag_name)

        for tag in tags:
            link = tag.get(attribute)

            if not link:
                continue

            # internal Jahia links
            if link.startswith("###page"):
                uuid = link[link.rfind('/') + 1:]

                if uuid in self.pages_by_uuid:
                    page = self.pages_by_uuid[uuid]

                    new_link = page.contents[box.page_content.language].path

                    tag[attribute] = new_link

                    self.internal_links += 1
            # some weird internal links look like :
            # /cms/op/edit/PAGE_NAME or
            # /cms/site/SITE_NAME/op/edit/lang/LANGUAGE/PAGE_NAME
            elif "/op/edit/" in link:
                new_link = link[link.index("/op/edit") + 8:]

                if new_link.startswith("/lang/"):
                    new_link = new_link[8:]

                tag[attribute] = new_link

            # absolute links rewritten as relative links
            elif link.startswith("http://" + self.server_name) or \
                    link.startswith("https://" + self.server_name):

                new_link = link[link.index(self.server_name) + len(self.server_name):]

                tag[attribute] = self.full_path(new_link)

                self.absolute_links += 1
            # file links
            elif link.startswith("###file"):
                new_link = link[link.index('/files/'):]

                if "?" in new_link:
                    new_link = new_link[:new_link.index("?")]

                tag[attribute] = self.full_path(new_link)

                self.file_links += 1
            # those are files links we already fixed, so we pass
            elif link.startswith(self.root_path + "/files/"):
                pass
            # external links
            elif link.startswith("http://") or link.startswith("https://"):
                self.external_links += 1
            # data links
            elif link.startswith("data:"):
                self.data_links += 1
            # mailto links
            elif link.startswith("mailto:"):
                self.mailto_links += 1
            # unknown links
            else:
                logging.debug("found unknown link %s", link)
                self.unknown_links += 1

        box.content = str(soup)

    def generate_report(self):
        """Generate the report of what has been parsed"""

        self.num_files = len(self.files)

        self.num_pages = len(self.pages_by_pid.values())

        # calculate the total number of boxes by type
        # dict key is the box type, dict value is the number of boxes

        for box in self.get_all_boxes():
            if box.type in self.num_boxes:
                self.num_boxes[box.type] = self.num_boxes[box.type] + 1
            else:
                self.num_boxes[box.type] = 1

        self.report = """
Parsed for %s :

  - %s files

  - %s pages :

""" % (self.server_name, self.num_files, self.num_pages)

        for num, count in self.num_boxes.items():
            self.report += "    - %s %s boxes\n" % (count, num)

        self.report += "    - %s internal links\n" % self.internal_links
        self.report += "    - %s absolute links\n" % self.absolute_links
        self.report += "    - %s external links\n" % self.external_links
        self.report += "    - %s file links\n" % self.file_links
        self.report += "    - %s mailto links\n" % self.mailto_links
        self.report += "    - %s data links\n" % self.data_links
        self.report += "    - %s unknown links\n" % self.unknown_links
