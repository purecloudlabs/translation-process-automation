import os, sys, re, requests, json, codecs
from requests.exceptions import ConnectionError
from hashlib import sha1
from TransifexCredsConfigurationClass import TransifexCredsConfiguration

class TransifexTranslationDownload:
    def __init__(self):
        self.path = str()
        self.status = str()
        self.errors = 0

class TransifexRepository:
    def __init__(self, project_name, log_dir):
        self._transifex_username = str()
        self._transifex_userpasswd = str()
        self._project_name = project_name
        self._log_dir = log_dir
        self._TRANSIFEX_CREDS_FILE = 'transifex_creds.yaml'

    def _set_transifex_creds(self):
        if not os.path.isfile(self._TRANSIFEX_CREDS_FILE):
            sys.stderr.write("Transifex creds config file NOT found: {}.\n".format(self._TRANSIFEX_CREDS_FILE))
            return False

        t = TransifexCredsConfiguration()
        if not t.parse(self._TRANSIFEX_CREDS_FILE):
            sys.stderr.write("Failed to parse Transifex creds config file: {}\n".format(self._TRANSIFEX_CREDS_FILE))
            return False
        else:
            self._transifex_username = t.get_username()
            self._transifex_userpasswd = t.get_userpasswd()
            return True

    def generate_project_slug(self, project_name):
        """ A project slug format is
                inin-[a-z0-9-]+
            [a-z0-9-]+ part is generated from project name in translation config.
        """
        s = project_name.strip().lower()
        slug = 'inin-{}'.format(re.sub('[^a-z0-9]', '-', s))
        # TODO --- need to check w/ Trnaisfex support about this limit.
        #if len(slug) > self._TRANSIFEX_PROJECT_SLUG_LEN:
        #    sys.stderr.write("Project slug excceeded max length.")
        #    sys.stderr.write("Generated: {}".format(slug))
        #    return None

        return slug

    def generate_resource_slug(self, seeds):
        """ A resource slug format is
                inin-<sha1>
            <sha1> is generated by given string 'seeds'.
        """
        text = ''.join(seeds).encode('utf-8')
        return 'inin-{}'.format(sha1(text).hexdigest())

    def import_resource(self, repository_name, resource_path, import_path):
        pslug = self.generate_project_slug(self._project_name)
        if not pslug:
            return False
        else:
            sys.stdout.write("Destination project: {} ({})\n".format(pslug, self._project_name))

        rslug = self.generate_resource_slug([repository_name, resource_path])
        if not rslug:
            return False
        else:
            sys.stdout.write("Destination Resource: {}\n".format(rslug))

        return self._upload(pslug, rslug, import_path)

    def _get_language_stats(self, project_slug, resource_slug, language_code):
        if not (self._transifex_username and self._transifex_userpasswd):
            if not self._set_transifex_creds():
                return None

        url = 'http://www.transifex.com/api/2/project/' + project_slug + '/resource/' + resource_slug + '/stats/' + language_code + '/'
        try:
            r = requests.get(url, auth=(self._transifex_username, self._transifex_userpasswd))
        except ConnectionError as e:
            sys.stderr.write("{}\n".format(e))
            return None
        else:
            return r

    def _is_review_completed(self, stats_response):
        if stats_response['reviewed_percentage'] == '100%':
            return True
        else:
            return False

    def _upload(self, project_slug, resource_slug, import_file_path):
        if not (self._transifex_username and self._transifex_userpasswd):
            if not self._set_transifex_creds():
                return None

        url = 'http://www.transifex.com/api/2/project/' + project_slug + '/resource/' + resource_slug + '/content/'
        headers = {'Content-type': 'multipart/form-data'}
        files = {'file': (import_file_path, open(import_file_path, 'rb'), 'multipart/form-data', {'Expires': '0'})}
        try:
            r = requests.put(url, auth=(self._transifex_username, self._transifex_userpasswd), files=files)
        except ConnectionError as e:
            sys.stderr.write("{}\n".format(e))
            return False
        else:
            if r.status_code == 200 or r.status_code == 201:
                sys.stdout.write("Uploaded.\n")
                sys.stdout.write(r.text)
                os.rename(import_file_path, os.path.join(self._log_dir, resource_slug + '_transifex_imported'))
                return True
            else:
                sys.stderr.write("Failed to upload. Status code: {}, pslug: '{}', rslug: '{}'\n".format(r.status_code, project_slug, resource_slug))
                os.rename(import_file_path, os.path.join(self._log_dir, resource_slug + '_import_failed'))
                return False

    def download_translation(self, repository_name, resource_path, language_code):
        download = TransifexTranslationDownload()        
        pslug = self.generate_project_slug(self._project_name)
        if not pslug:
            download.error += 1
            download.status = "Failed to generate project slug."
            return download

        rslug = self.generate_resource_slug([repository_name, resource_path])
        if not rslug:
            download.error += 1
            download.status = "Failed to generate resource slug."
            return download

        r = self._get_language_stats(pslug, rslug, language_code)
        if r:
            if r.status_code == 200 or r.status_code == 201:
                if self._is_review_completed(r.json()):
                    self._download_translation(download, pslug, rslug, language_code)
                else:
                    download.status = "Review not completed: {}, pslug: '{}', rslug: '{}'".format(language_code, pslug, rslug)   
            elif r.status_code == 404:
                # TODO --- nofity translation owner so that s/he can add translation language to transifex (w/ assuming 
                #          the language is a new scope for the project (b/c developer added it))
                download.errors += 1
                download.status = "Language not found: {}, pslug: '{}', rslug: '{}'".format(language_code, pslug, rslug)   
            else:
                download.errors += 1
                download.status = "Failed to obtain language status: {}. Code: {}, pslug: '{}', rslug: '{}'".format(language_code, r.status_code, pslug, rslug)
        else:
            download.errors += 1
            download.status = "Failed to obtain language status: {}, pslug: '{}', rslug: '{}'.".format(language_code, pslug, rslug)

        return download

    def _download_translation(self, transifex_download_obj, project_slug, resource_slug, language_code):
        if not (self._transifex_username and self._transifex_userpasswd):
            if not self._set_transifex_creds():
                return None

        url = 'http://www.transifex.com/api/2/project/' + project_slug + '/resource/' + resource_slug + '/translation/' + language_code + '/?mode=reviewed'
        try:
            r =  requests.get(url, auth=(self._transifex_username, self._transifex_userpasswd))
        except ConnectionError as e:
            sys.stderr.write("{}\n".format(e))
            transifex_download_obj.errors += 1
            transifex_download_obj.status = "Failed to download translation."
            return
        else:
            if not (r.status_code == 200 or r.status_code == 201):
                transifex_download_obj.errors += 1
                transifex_download_obj.status = "Failed to download translation. Status: {}".format(r.status_code)
                return

        raw_download_path = os.path.join(self._log_dir, resource_slug + '_' + language_code + '_raw')
        if os.path.isfile(raw_download_path):
            os.remove(raw_download_path)
        if sys.version_info[0:1] == (2,):
            with codecs.open(raw_download_path, 'w', encoding='utf-8') as fo:
                fo.write(r.text)
        else:
            with open(raw_download_path, 'w') as fo:
                fo.write(r.text)

        with open(raw_download_path, 'r') as fi:
            try:
                j = json.load(fi)
            except ValueError as e:
                transifex_download_obj.errors += 1
                transifex_download_obj.status = "Failed read raw download. Reason: {}".format(e)
                return
            else:
                download_path = os.path.join(self._log_dir, resource_slug + '_' + language_code)
                if os.path.isfile(download_path):
                    os.remove(download_path)

                if sys.version_info[0:1] == (2,):
                    with codecs.open(download_path, 'w', encoding='utf-8') as fo:
                        fo.write(j['content'])
                else:
                    with open(download_path, 'w') as fo:
                        fo.write(j['content'])

                transifex_download_obj.path = os.path.abspath(download_path)
                transifex_download_obj.status = "Donloaded: {}".format(download_path)

