"""(c) All rights reserved. ECOLE POLYTECHNIQUE FEDERALE DE LAUSANNE, Switzerland, VPSI, 2017"""
import logging
import os
import subprocess
import timeit
from collections import OrderedDict
from datetime import timedelta, datetime

import simplejson
from bs4 import BeautifulSoup
from wordpress_json import WordpressJsonWrapper, WordpressError

from exporter.utils import Utils
from settings import WP_SUPERADMIN_USER, WP_SUPERADMIN_PASSWORD, WP_PATH, CONFIGURED_LANGUAGES


class WPExporter:
    # this file is used to save data for importing data
    TRACER_FILE_NAME = "tracer_importing.csv"

    # list of mapping Jahia url and Wordpress url
    urls_mapping = []

    def __init__(self, site, site_host, site_path, output_dir, wp_cli=None):
        """
        site is the python object resulting from the parsing of Jahia XML.
        site_host is the domain name.
        site_path is the url part of the site without the site_name.
        output_dir is the path where information files will be generated.
        wp_cli is the name of the container docker which contains wpcli.
        """
        self.site = site
        self.host = site_host
        self.path = site_path
        self.elapsed = 0
        self.report = {
            'pages': 0,
            'files': 0,
            'menus': 0,
            'failed_files': 0,
            'failed_menus': 0,
            'failed_widgets': 0,
        }
        # dictionary with the key 'wp_page_id' and the value 'wp_menu_id'
        self.menu_id_dict = {}
        self.cli_container = wp_cli or "wp-cli-%s" % self.site.name
        self.output_dir = output_dir

        # we use the python-wordpress-json library to interact with the wordpress REST API
        rest_api_url = "http://%s/%s/?rest_route=/wp/v2" % (self.host, self.path)
        logging.info("setting up API on '%s', with %s:xxxxxx", rest_api_url, WP_SUPERADMIN_USER)
        self.wp = WordpressJsonWrapper(rest_api_url, WP_SUPERADMIN_USER, WP_SUPERADMIN_PASSWORD)

    def wp_cli(self, command, stdin=None):
        """
        Wrapper around the WP-CLI (wp-cli.org),
        official wordpress command line interface)
        available in the docker container wpcli
        """
        try:
            cmd = "docker exec %s" % self.cli_container

            if stdin:
                cmd += " sh -c 'echo '\"'\"'"
                cmd += stdin
                cmd += "'\"'\"' |"
            cmd += " wp --allow-root --path='%s' %s" % (self.path, command)
            if stdin:
                cmd += "'"
            logging.debug("exec '%s'", cmd)
            return subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError as err:
            logging.error("%s - WP export - wp_cli failed : %s", self.site.name, err)
            return None

    def import_all_data_to_wordpress(self):
        """
        Import all data to worpdress via REST API and wp-cli
        """
        try:
            start_time = timeit.default_timer()
            tracer_path = os.path.join(self.output_dir, self.TRACER_FILE_NAME)

            self.align_languages()
            self.import_medias()
            self.import_pages()
            self.set_frontpage()
            self.populate_menu()
            self.import_sidebar()
            self.display_report()

            # log execution time
            elapsed = timedelta(seconds=timeit.default_timer() - start_time)
            logging.info("Data imported in %s", elapsed)

            # write a csv file
            with open(tracer_path, 'a', newline='\n') as tracer:
                tracer.write("%s, %s, %s, %s, %s, %s\n" % (
                    '{0:%Y-%m-%d %H:%M:%S}'.format(datetime.now()),
                    self.site.name,
                    str(elapsed),
                    self.report['failed_files'],
                    self.report['failed_menus'],
                    self.report['failed_widgets'],
                ))
                tracer.flush()

        except WordpressError as err:
            logging.error("%s - WP export - Exception while importing all data: %s", self.site.name, err)
            with open(tracer_path, 'a', newline='\n') as tracer:
                tracer.write("%s, ERROR %s\n" % (self.site.name, str(err)))
                tracer.flush()

    def align_languages(self):
        """
        In docker configuration we create 2 languages (fr, en) by default.
        If the current site is only in 1 language we need to delete the 'bad' language.
        """
        if len(self.site.languages) == 1:
            for lang in (CONFIGURED_LANGUAGES - set(self.site.languages)):
                logging.info("Deleting language %s", lang)
                self.wp_cli('pll lang delete %s' % lang)

    def import_medias(self):
        """
        Import medias to Wordpress
        """
        logging.info("{0:%Y-%m-%d %H:%M:%S} WP medias import start".format(datetime.now()))
        for file in self.site.files:
            wp_media = self.import_media(file)
            if wp_media:
                self.fix_file_links(file, wp_media)
                self.report['files'] += 1
        logging.info("{0:%Y-%m-%d %H:%M:%S} WP medias imported".format(datetime.now()))

    def import_media(self, media):
        """
        Import a media to Wordpress
        """
        file_path = media.path + '/' + media.name
        file = open(file_path, 'rb')

        files = {
            'file': file
        }

        wp_media_info = {
            # date
            # date_gmt
            'slug': media.path,
            # status
            'title': media.name,
            # author
            # comment_status
            # ping_status
            # meta
            # template
            # alt_text
            # caption
            # description
            # post
        }
        files = files
        try:
            logging.debug("WP media information %s", wp_media_info)
            wp_media = self.wp.post_media(data=wp_media_info, files=files)
            return wp_media
        except Exception as e:
            logging.error("%s - WP export - media failed: %s", self.site.name, e)
            self.report['failed_files'] += 1

    def fix_file_links(self, file, wp_media):
        """Fix the links pointing to the given file"""

        if "/files" not in file.path:
            return

        # the old url is the file relative path
        old_url = file.path[file.path.rfind("/files"):]

        # the new url is the wp media source url
        new_url = wp_media['source_url']

        tag_attribute_tuples = [("a", "href"), ("img", "src"), ("script", "src")]

        for box in self.site.get_all_boxes():

            soup = BeautifulSoup(box.content, 'html.parser')

            for tag_name, tag_attribute in tag_attribute_tuples:

                self.fix_links_in_tag(
                    soup=soup,
                    old_url=old_url,
                    new_url=new_url,
                    tag_name=tag_name,
                    tag_attribute=tag_attribute)

            # save the new box content
            box.content = str(soup)

    def fix_page_content_links(self, wp_pages):
        """
        Fix all the links once we know all the WordPress pages urls
        """
        for wp_page in wp_pages:

            content = ""

            if "content" in wp_page:
                content = wp_page["content"]["raw"]
            else:
                logging.error("Expected content for page %s" % wp_page)

            soup = BeautifulSoup(content, 'html.parser')

            for url_mapping in self.urls_mapping:

                old_url = url_mapping["jahia_url"]
                new_url = url_mapping["wp_url"]

                self.fix_links_in_tag(
                    soup=soup,
                    old_url=old_url,
                    new_url=new_url,
                    tag_name="a",
                    tag_attribute="href"
                )

            # update the page
            wp_id = wp_page["id"]

            content = str(soup)

            self.update_page_content(page_id=wp_id, content=content)

    def fix_links_in_tag(self, soup, old_url, new_url, tag_name, tag_attribute):
        """Fix the links in the given tag"""

        tags = soup.find_all(tag_name)

        for tag in tags:
            link = tag.get(tag_attribute)

            if not link:
                continue

            if link == old_url:
                logging.debug("Changing link from %s to %s" % (old_url, new_url))
                tag[tag_attribute] = new_url

    def update_page(self, page_id, title, content):
        """
        Import a page to Wordpress
        """
        wp_page_info = {
            # date: auto => date/heure du jour
            # date_gmt: auto => date/heure du jour GMT
            # 'slug': slug,
            # 'status': 'publish',
            # password
            'title': title,
            'content': content,
            # author
            # excerpt
            # featured_media
            # comment_status: 'closed'
            # ping_status: 'closed'
            # format
            # meta
            # sticky
            # template
            # categories
            # tags
        }
        return self.wp.post_pages(page_id=page_id, data=wp_page_info)

    def update_page_content(self, page_id, content):
        """Update the page content"""
        data = {"content": content}
        return self.wp.post_pages(page_id=page_id, data=data)

    def import_page(self, slug, title, content):

        wp_page_info = {
            # date: auto => date/heure du jour
            # date_gmt: auto => date/heure du jour GMT
            'slug': slug,
            'status': 'publish',
            # password
            'title': title,
            'content': content,
            # author
            # excerpt
            # featured_media
            # comment_status: 'closed'
            # ping_status: 'closed'
            # format
            # meta
            # sticky
            # template
            # categories
            # tags
        }

        return self.wp.post_pages(data=wp_page_info)

    def import_pages(self):
        """
        Import all pages of jahia site to Wordpress
        """

        # keep the pages for fixing the links later
        wp_pages = []

        for page in self.site.pages_by_pid.values():

            contents = {}
            info_page = OrderedDict()

            for lang in page.contents.keys():
                contents[lang] = ""

                # create the page content
                for box in page.contents[lang].boxes:
                    contents[lang] += box.content

                info_page[lang] = {
                    'post_name': page.contents[lang].path,
                    'post_status': 'publish',
                }

            cmd = "pll post create --post_type=page --stdin --porcelain"
            stdin = simplejson.dumps(info_page)

            result = self.wp_cli(command=cmd, stdin=stdin)
            if not result:
                error_msg = "Could not created page"
                logging.error(error_msg)
                continue

            wp_ids = result.decode("utf-8").split()

            if len(wp_ids) != len(contents):
                error_msg = "%s page created is not expected : %s" % (len(wp_ids), len(contents))
                logging.error(error_msg)
                continue

            for wp_id, (lang, content) in zip(wp_ids, contents.items()):
                wp_page = self.update_page(page_id=wp_id, title=page.contents[lang].title, content=content)

                # prepare mapping for the nginx conf generation
                mapping = {
                    'jahia_url': page.contents[lang].path,
                    'wp_url': wp_page['link']
                }

                self.urls_mapping.append(mapping)

                logging.info("WP page '%s' created", wp_page['link'])

                # keep WordPress ID for further usages
                page.contents[lang].wp_id = wp_page['id']

                wp_pages.append(wp_page)

            self.report['pages'] += 1

        self.fix_page_content_links(wp_pages)

        self.create_sitemaps()

        self.update_parent_ids()

    def update_parent_ids(self):
        """
        Update all pages to define the pages hierarchy
        """
        for page in self.site.pages_by_pid.values():
            for lang, page_content in page.contents.items():

                if page.parent and page_content.wp_id:
                    parent_id = page.parent.contents[lang].wp_id
                    wp_page_info = {
                        'parent': parent_id
                    }
                    self.wp.post_pages(page_id=page.contents[lang].wp_id, data=wp_page_info)

    def create_sitemaps(self):

        info_page = OrderedDict()

        for lang in self.site.homepage.contents.keys():
            # create sitemap page

            info_page[lang] = {
                'post_name': 'sitemap',
                'post_status': 'publish',
            }

        cmd = "pll post create --post_type=page --stdin --porcelain"
        stdin = simplejson.dumps(info_page)
        result = self.wp_cli(command=cmd, stdin=stdin)

        sitemap_ids = result.decode("utf-8").split()
        for sitemap_wp_id, lang in zip(sitemap_ids, info_page.keys()):
            wp_page = self.update_page(
                page_id=sitemap_wp_id,
                title='sitemap',
                content='[simple-sitemap show_label="false" types="page orderby="menu_order"]'
            )
            self.create_footer_menu_for_sitemap(sitemap_wp_id=wp_page['id'], lang=lang)

    def import_sidebar(self):
        """
        import sidebar via wpcli
        """
        try:
            for lang in self.site.homepage.contents.keys():
                for box in self.site.homepage.contents[lang].sidebar.boxes:
                    content = Utils.escape_quotes(box.content)
                    cmd = 'widget add black-studio-tinymce page-widgets ' \
                          '--title="%s" --text="%s"' % (box.title, content)
                    self.wp_cli(cmd)

                # Import sidebar for one language only
                break

            logging.info("WP all sidebar imported")

        except WordpressError as e:
            logging.error("%s - WP export - widget failed: %s", self.site.name, e)
            self.report['failed_widgets'] += 1

    def create_footer_menu_for_sitemap(self, sitemap_wp_id, lang):
        """
        Create footer menu for sitemap page
        """
        footer_name = "footer_nav"
        if lang != 'fr':
            footer_name += "-%s" % lang
        self.wp_cli('menu item add-post %s %s --porcelain' % (footer_name, sitemap_wp_id))

        # Create footer menu
        cmd = "menu item add-custom %s Accessibility http://www.epfl.ch/accessibility.en.shtml​" % footer_name
        self.wp_cli(cmd)

        # legal notice
        cmd = "menu item add-custom %s 'Legal Notice' http://mediacom.epfl.ch/disclaimer-en​" % footer_name
        self.wp_cli(cmd)

        # Report
        self.report['menus'] += 2

    def create_submenu(self, page, lang, menu_name):
        """
        Create recursively submenus.
        """
        if page not in self.site.homepage.children \
                and lang in page.contents \
                and page.parent.contents[lang].wp_id in self.menu_id_dict:

            parent_menu_id = self.menu_id_dict[page.parent.contents[lang].wp_id]

            command = 'menu item add-post %s %s --parent-id=%s --porcelain' \
                      % (menu_name, page.contents[lang].wp_id, parent_menu_id)
            menu_id = self.wp_cli(command)
            if not menu_id:
                logging.warning("Menu not created for page %s" % page.pid)
            else:
                self.menu_id_dict[page.contents[lang].wp_id] = Utils.get_menu_id(menu_id)
                self.report['menus'] += 1

        if page.has_children():
            for child in page.children:
                self.create_submenu(child, lang, menu_name)

    def populate_menu(self):
        """
        Add pages into the menu in wordpress.
        This menu needs to be created before hand.
        """
        try:
            # Create homepage menu
            for lang, page_content in self.site.homepage.contents.items():

                menu_name = "Main"
                if lang != 'fr':
                    menu_name += '-%s' % lang

                cmd = 'menu item add-post %s %s --classes=link-home --porcelain'
                menu_id = self.wp_cli(cmd % (menu_name, page_content.wp_id))
                if not menu_id:
                    logging.warning("Menu not created for page  %s" % page_content.pid)
                else:
                    self.menu_id_dict[page_content.wp_id] = Utils.get_menu_id(menu_id)
                    self.report['menus'] += 1

                # Create children of homepage menu
                for homepage_child in self.site.homepage.children:

                    if lang not in homepage_child.contents:
                        logging.warning("Page not translated %s" % homepage_child.pid)
                        continue

                    if homepage_child.contents[lang].wp_id:
                        cmd = 'menu item add-post %s %s --porcelain'
                        menu_id = self.wp_cli(cmd % (menu_name, homepage_child.contents[lang].wp_id))
                        if not menu_id:
                            logging.warning("Menu not created %s for page " % homepage_child.pid)
                        else:
                            self.menu_id_dict[homepage_child.contents[lang].wp_id] = Utils.get_menu_id(menu_id)
                            self.report['menus'] += 1

                    # create recursively submenus
                    self.create_submenu(homepage_child, lang, menu_name)

                logging.info("WP menus populated")

        except Exception as e:
            logging.error("%s - WP export - menu failed: %s", self.site.name, e)
            self.report['failed_menus'] += 1

    def set_frontpage(self):
        """
        Use wp-cli to set the two worpress options needed fotr the job
        """
        # sanity check on homepage
        if not self.site.homepage:
            raise Exception("No homepage defined for site")

        # call wp-cli
        self.wp_cli('option update show_on_front page')

        for lang in self.site.homepage.contents.keys():
            frontpage_id = self.site.homepage.contents[lang].wp_id
            result = self.wp_cli('option update page_on_front %s' % frontpage_id)
            if result is not None:
                # Set on only one language is sufficient
                logging.info("WP frontpage setted")
                break

    def delete_all_content(self):
        """
        Delete all content WordPress
        """
        self.delete_medias()
        self.delete_pages()
        self.delete_widgets()

    def delete_medias(self):
        """
        Delete medias in WordPress via WP REST API
        HTTP delete  http://.../wp-json/wp/v2/media/1761?force=true
        """
        logging.info("Deleting medias...")
        medias = self.wp.get_media(params={'per_page': '100'})
        while len(medias) != 0:
            for media in medias:
                self.wp.delete_media(media_id=media['id'], params={'force': 'true'})
            medias = self.wp.get_media(params={'per_page': '100'})
        logging.info("All medias deleted")

    def delete_pages(self):
        """
        Delete all pages in Wordpress via WP REST API
        HTTP delete /wp-json/wp/v2/pages/61?force=true
        """
        pages = self.wp.get_pages(params={'per_page': '100'})
        while len(pages) != 0:
            for page in pages:
                self.wp.delete_pages(page_id=page['id'], params={'force': 'true'})
            pages = self.wp.get_pages(params={'per_page': '100'})
        logging.info("All pages and menus deleted")

    def delete_widgets(self):
        """
        Delete all widgets
        """
        cmd = "widget list page-widgets --fields=id --format=csv"
        widgets_id_list = self.wp_cli(cmd).decode("UTF-8").split("\n")[1:-1]
        for widget_id in widgets_id_list:
            cmd = "widget delete " + widget_id
            self.wp_cli(cmd)
        logging.info("All widgets deleted")

    def display_report(self):
        """
        Display report
        """
        print("Imported in WordPress:\n"
              "- {files}s files\n"
              "- {pages}s pages\n"
              "- {menus}s menus\n"
              "\n"
              "Errors:\n"
              "- {failed_files}s files\n"
              "- {failed_menus}s menus\n"
              "- {failed_widgets}s widgets\n".format(**self.report))

    def generate_nginx_conf_file(self):
        """
        Generates a nginx configuration file containing
        the rewrites of the pages jahia in WordPress page.
        """
        the_dict = {
            'site_name': self.site.name,
            'WP_PATH': WP_PATH,
        }

        first_part = "server {{\n" \
                     "\tserver_name {site_name}.epfl.ch ;\n" \
                     "\treturn 301 $scheme://test-web-static.epfl.ch/{WP_PATH}/{site_name}$request_uri;\n" \
                     "}}\n" \
                     "\n" \
                     "server {{\n" \
                     "\tlisten\t80;\n" \
                     "\tlisten\t[::]:80;\n" \
                     "\tserver_name\ttest-web-static.epfl.ch;\n" \
                     "\n".format(**the_dict)

        last_part = "\n" \
                    "\tlocation / {\n" \
                    "\t\tproxy_pass\thttp://traefik/;\n" \
                    "\t}\n" \
                    "}\n"

        # Add the first part of the content file
        content = first_part

        # Add all rewrite jahia URI to WordPress URI
        for element in self.urls_mapping:

            the_dict['jahia_url'] = element['jahia_url'][1:]
            the_dict['wp_url'] = element['wp_url'].split("/")[3]

            line = "\trewrite ^/{WP_PATH}/{site_name}/{jahia_url}$ " \
                   "/{WP_PATH}/{site_name}/{wp_url} permanent;\n".format(**the_dict)
            content += line

        # Add the last part of the content file
        content += last_part

        # Set the file name
        file_name = os.path.join(self.output_dir, 'jahia-%s.conf' % self.site.name)

        # Open the file in write mode
        with open(file_name, 'a') as f:
            f.write(content)
