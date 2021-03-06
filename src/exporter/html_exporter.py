#!/usr/local/bin/python
"""(c) All rights reserved. ECOLE POLYTECHNIQUE FEDERALE DE LAUSANNE, Switzerland, VPSI, 2017"""

import os
import shutil
import logging

from bs4 import BeautifulSoup
from jinja2 import Environment, PackageLoader, select_autoescape


class HTMLExporter:

    env = Environment(
        loader=PackageLoader('exporter', 'templates'),
        autoescape=select_autoescape(['html', 'xml'])
    )

    def __init__(self, site, out_path):

        # if True we add an .html extension to pages without an extension
        self.option_add_html_extension = True
        # if True we extract the site files. Set to False to speed up the export
        self.option_extract_files = True

        self.site = site
        self.out_path = out_path
        self.full_path = out_path + site.root_path

        # to use in templates
        self.root_path = site.root_path

        # add the .html extension
        if self.option_add_html_extension:
            self.add_html_extension()

        # create output path if necessary
        if not os.path.exists(self.full_path):
            logging.debug("created output dir %s", self.full_path)
            os.makedirs(self.full_path)

        # extract all the files
        if self.option_extract_files:
            self.extract_files()

        # generate the Pages for each language
        for language in site.languages:
            self.language = language
            self.sitemap_content = ""
            self.navigation = ""

            self.generate_pages()

    def add_html_extension(self):
        """Add an .html extension to pages without an extension"""
        logging.debug("Adding .html extension to pages without extension")

        # first fix all the page_content paths
        for page in self.site.pages_by_pid.values():
            for page_content in page.contents.values():
                dirname = os.path.dirname(page_content.path)
                basename = os.path.basename(page_content.path)

                if "." not in basename:
                    basename += ".html"
                    page_content.path = os.path.join(dirname, basename)

        # next fix all the links in the boxes
        for box in self.site.get_all_boxes():
            soup = BeautifulSoup(box.content, 'html.parser')

            tags = soup.find_all("a")

            for tag in tags:
                link = tag.get("href")

                if not link:
                    continue

                # we change only relative links
                if link.startswith("/"):
                    dirname = os.path.dirname(link)
                    basename = os.path.basename(link)

                    if "." not in basename:
                        basename += ".html"

                        tag["href"] = os.path.join(dirname, basename)

            box.content = str(soup)

    def generate_pages(self):
        """Generate the pages & the sitemap"""
        logging.debug("Generating pages for language %s", self.language)

        # update the boxes data
        self.update_boxes_data()

        # navigation
        self.generate_navigation(self.site.homepage)

        # regular pages
        template = self.env.get_template('epfl-sidebar.html')

        for page in self.site.pages_by_pid.values():
            # check if the page exists in this language
            if self.language not in page.contents:
                continue

            page_content = page.contents[self.language]
            content = template.render(page_content=page_content, site=self.site, exporter=self)

            self.generate_page(path=page_content.path, content=content)

        # sitemap
        template = self.env.get_template('epfl-sitemap.html')

        # the sitemap is not a real Page, we create a dict with
        # the informations we need in the template
        sitemap = {}
        sitemap["language"] = self.language

        self.generate_sitemap_content(self.site.homepage)

        content = template.render(page_content=sitemap, site=self.site, exporter=self)

        self.generate_page(
            path="%s/sitemap-%s.html" % (self.site.root_path, self.language),
            content=content)

    def update_boxes_data(self):
        """Update the boxes data"""
        logging.debug("Updating boxes data")

        for box in self.site.get_all_boxes():
            if box.type == "toggle":
                # toggle title
                content = "<h3 data-widget='collapse'>%s</h3>" % box.title
                # toggle content
                content += "<div>%s</div>" % box.content

                box.content = content

                # we don't want to show the box title
                box.title = None

            # all other box types, we just enclose them in a div
            else:
                box.content = "<div>" + box.content + "</div>"

    def generate_page(self, path, content):
        """Generate a page"""
        path = "%s%s" % (self.out_path, path)

        directory = os.path.dirname(path)

        # create the destination directory if necessary
        if not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)

        logging.debug("Generating page %s", path)

        file = open(path, "w")

        file.write(content)

        file.close()

    def generate_navigation(self, page):
        """
        Generate the navigation content. This is a recursive method
        """

        # check if the page exists in this language
        if self.language not in page.contents:
            return

        if not page.is_homepage():
            # current page
            self.navigation_spacer(page)
            self.navigation += "<li class='nav-item'><a class='nav-link' href='%s'>%s</a>" % \
                               (page.contents[self.language].path,
                                page.contents[self.language].title)

        if page.has_children():
            if not page.is_homepage():
                self.navigation += "\n"
                self.navigation_spacer(page)
                self.navigation += "<ul class='nav-list nav-vertical' data-widget='menu'>\n"

            for child in page.children:
                # recursive call
                self.generate_navigation(child)

            if not page.is_homepage():
                self.navigation_spacer(page)
                self.navigation += "</ul>\n</li>\n"
        else:
            if not page.is_homepage():
                self.navigation += "</li>\n"

    def navigation_spacer(self, page):
        """Add spaces according to the page level"""
        for i in range(page.level - 1):
            self.navigation += "  "

    def generate_sitemap_content(self, page):
        """
        Generate the sitemap content. This is a recursive method
        """
        # top <ul> for the homepage

        # check if the page exists in this language
        if self.language not in page.contents:
            return

        if page.is_homepage():
            self.sitemap_content += "<ul>"

        # current page
        self.sitemap_content += "<li><a href='%s'>%s</a>" %\
            (page.contents[self.language].path,
             page.contents[self.language].title)

        if page.has_children():
            self.sitemap_content += "<ul>"

            for child in page.children:
                # recursive call
                self.generate_sitemap_content(child)

            self.sitemap_content += "</ul></li>"
        else:
            self.sitemap_content += "</li>"

        # top <ul> for the homepage
        if page.is_homepage():
            self.sitemap_content += "</ul>"

    @staticmethod
    def files_to_ignore(dirs, files):
        return ["thumbnail", "thumbnail2"]

    def extract_files(self):
        """Extract the files"""

        if not os.path.isdir(os.path.join(self.site.base_path, "content")):
            if len(self.site.files) == 0:
                logging.info("no files found for %s", self.site.base_path)
            else:
                logging.warning("no files found for %s whereas %s expected" %
                                (self.site.base_path, len(self.site.files)))
            return

        start = "%s/content/sites/%s/files" % (self.site.base_path, self.site.name)
        dst = "%s/files" % self.full_path

        if os.path.exists(dst):
            logging.debug("%s dir already exists. Wiping it out..." % dst)
            shutil.rmtree(dst)

        logging.debug("Copying files from %s to %s", start, dst)

        # copy all files as they are
        shutil.copytree(start, dst, ignore=HTMLExporter.files_to_ignore)

        # move all files one level up: out of the directory with same name
        for (path, dirs, files) in os.walk(dst):
            name = os.path.basename(path)
            if len(files) == 1 and files[0] == name:
                file_path = os.path.join(path, name)
                tmp_path = os.path.normpath(os.path.join(path, '..', '_%s' % name))
                shutil.move(file_path, tmp_path)
                os.rmdir(path)
                shutil.move(tmp_path, path)
