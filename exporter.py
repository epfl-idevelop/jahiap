#!/usr/local/bin/python

from jinja2 import Environment, PackageLoader, select_autoescape

import os

from settings import *


class Exporter:

    def __init__(self, site, out_path):

        self.site = site
        self.out_path = out_path

        # create the output path if necessary
        if not os.path.exists(self.out_path):
            cmd = "mkdir %s" % self.out_path
            os.system(cmd)

        self.generate_pages()
        self.extract_files()

    def generate_pages(self):
        """Generate the pages"""

        env = Environment(
            loader=PackageLoader('exporter', 'templates'),
            autoescape=select_autoescape(['html', 'xml'])
        )

        template = env.get_template('epfl-en.html')

        for page in self.site.pages.values():

            path = "%s/%s" % (self.out_path, page.name)

            content = template.render(page=page)

            html_file = open(path, "w")

            html_file.write(content)

            html_file.close()

    def extract_files(self):
        """Extract the files"""

        start = "%s/content/sites/%s/files" % (BASE_PATH, SITE_NAME)

        for (path, dirs, files) in os.walk(start):
            for file in files:
                # we exclude the thumbnails
                if "thumbnail" == file or "thumbnail2" == file:
                    continue

                src = "%s/%s" % (path, file)

                dst = OUT_PATH + src[src.index("files/") - 1:]

                dst = dst[:dst.rindex("/")]

                parent = dst[:dst.rindex("/")]

                # create the parent directory if necessary
                if not os.path.exists(parent):
                    cmd = "mkdir -p '%s'" % parent
                    os.system(cmd)

                # now copy the file
                cmd = "cp '%s' '%s'" % (src, dst)
                os.system(cmd)
