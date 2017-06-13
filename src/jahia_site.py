"""(c) All rights reserved. ECOLE POLYTECHNIQUE FEDERALE DE LAUSANNE, Switzerland, VPSI, 2017"""

"""
This file is named jahia_site to avoid a conflict with Site https://docs.python.org/3/library/site.html
"""
import os

from box import Box
from file import File
from link import Link
from page import Page
from page_content import PageContent
from utils import Utils


class Site:
    """A Jahia Site. Have 1 to N Pages"""

    def __init__(self, base_path, name):
        self.base_path = base_path
        self.name = name

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

        # the pages. We have a both list and a dict.
        # The dict key is the page id, and the dict value is the page itself
        self.pages = []
        self.pages_dict = {}

        # set for convenience, to avoid:
        #   [p for p in self.pages if p.is_homepage()][0]
        self.homepage = None

        # the files
        self.files = []

        # parse the data
        self.parse_data()

        # generate the report
        self.report = ""

        self.generate_report()

    def parse_data(self):
        """Parse the Site data"""

        # do the parsing
        self.parse_site_params()
        self.parse_breadcrumb()
        self.parse_footer()
        self.parse_pages()
        self.parse_pages_content()
        self.parse_files()

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

            breadcrumb_link = dom.getElementsByTagName("breadCrumbLink")[0]

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
                if pid in self.pages_dict:
                    continue

                page = Page(self, xml_page)

                # flag the homepage for convenience
                if page.is_homepage():
                    self.homepage = page

                # add the Page to the Site
                self.pages.append(page)
                self.pages_dict[page.pid] = page

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
                page = self.pages_dict[pid]
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

    def belongs_to(self, element, page):
        """Check if the given element belongs to the given page"""
        parent = element.parentNode

        while "jahia:page" != parent.nodeName:
            parent = parent.parentNode

        return page.pid == parent.getAttribute("jahia:pid")

    def generate_report(self):
        """Generate the report of what has been parsed"""

        num_files = len(self.files)

        num_pages = len(self.pages)

        # calculate the total number of boxes by type
        # dict key is the box type, dict value is the number of boxes
        num_boxes = {}

        for page in self.pages:
            for page_content in page.contents.values():
                for box in page_content.boxes:
                    if box.type in num_boxes:
                        num_boxes[box.type] = num_boxes[box.type] + 1
                    else:
                        num_boxes[box.type] = 1

        self.report = """
Found :

  - %s files

  - %s pages :

""" % (num_files, num_pages)

        for num, count in num_boxes.items():
            self.report += "    - %s %s boxes\n" % (count, num)
