#!/usr/bin/env python3
# -*- coding: iso-8859-15 -*-

# With contributions by Samba Fall, 2014

# Copyright (c) 2011, Chema Gonzalez (chema@cal.berkeley.edu)
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in
#       the documentation and/or other materials provided with the.
#       distribution
#     * Neither the name of the copyright holder nor the names of its
#       contributors may be used to endorse or promote products derived
#       from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDER AND CONTRIBUTORS ``AS
# IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER AND CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES LOSS OF USE, DATA, OR
# PROFITS OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
- intro
    - a python module implementing an MHTML creator/parser

- interesting functions
    - libmhtml.get(url)
    - libmhtml.parse(contents)

- usage
    - get an URL and MTHML'ize it
        > ./libmhtml.py http://www.nytimes.com /tmp/nytimes.mht
    - get an MHTML file and convert it into different files
        > mkdir /tmp/ex
        > ./libmhtml.py -p /tmp/nytimes.mht /tmp/ex/

"""

__version__ = '0.0.5'

import sys
import os
import re
import getopt
import copy
import urllib.parse
import urllib.request
import time
import imghdr
import quopri
import base64
from io import BytesIO
from mimetypes import guess_type
from bs4 import BeautifulSoup as BS


# default values
default = {
    'debug': 0,
    'operation': 'get',
    'base64_mime_types': ['image/png', 'image/x-icon'],
    'qp_mime_types': ['text/css', 'text/javascript'],
    'ignore_mime_types': ['application/rss+xml']
}


def q_encode(s, enc):
    # perform quoted-printable encoding
    s = quopri.encodestring(as_bytes(s))
    # encode invalid characters ('?' and '_') and the space
    substitutions = {b'\?': b'=3F', b'_': b'=5F', b' ': b'_'}
    for symbol, sub in substitutions.items():
        pat = re.compile(symbol)
        s = pat.sub(sub, s)
    # return q-encoded title
    out = "=?%s?Q?%s?=" % (enc, as_str(s))
    return out


def as_str(s):
    return s.decode() if isinstance(s, bytes) else s


def as_bytes(s):
    return s.encode() if isinstance(s, str) else s


def ext2mime(t):
    if 'gif' in t:
        return 'image/gif'
    elif 'png' in t:
        return 'image/png'
    elif 'jpeg' or 'jpg' in t:
        return 'image/jpeg'
    elif 'ico' in t:
        return 'image/x-icon'
    elif 'bm' or 'bmp' in t:
        return 'image/bmp'
    else:
        return None


def add_header(subject, date, boundary):
    out = """From: <saved by libmhtml.py>
Subject: %s
Date: %s
MIME-Version: 1.0
Content-Type: multipart/related;
    type="text/html";
    boundary="%s"
""" % (subject, date, boundary)

    return out


def add_part(ptype, boundary, content_type, url, contents):
    # add part header
    out = """\n--%s
Content-Type: %s
Content-Transfer-Encoding: %s
Content-Location: %s

""" % (boundary, content_type, ptype, url)
    # add part body
    contents = as_bytes(contents)
    if ptype == 'quoted-printable':
        out += as_str(quopri.encodestring(contents))
    elif ptype == 'base64':
        # append contents as base64
        s = as_str(base64.b64encode(contents))
        b64_text = '\n'.join(s[pos:pos+76] for pos in range(0, len(s), 76))
        out += b64_text
    else:
        print("Unknown mime type: \"%s\"" % ptype)
        sys.exit(-1)
    return out


def get_html_url(vals, url):
    if vals['debug'] > 1:
        print("processing %s" % url)
    # download url
    try:
        response = urllib.request.urlopen(url)
        html_code = response.read()
    except Exception:
        # 404 error
        error_str = "URL down: %s" % url
        return -1, error_str
    return 0, html_code


# \brief Get an URL and MHTML'ize it
# 
# Gets an URL, parse it, and then gets the linked images ('<img src=...>')
# and links ('<link .*href=...>'). Bundles everything into an MHTML file
# 
# \param[in,out] name Description
# \param[in] name Description
# \retval type (None) Error code (0 if OK, <0 if problems)
def get_url(vals, url):
    # get main page
    (res, main_page) = get_html_url(vals, url)
    soup = BS(as_str(main_page))
    if res < 0:
        return res, main_page

    # get title
    tag = soup.find('title')
    title = tag.text if tag else ''

    # get encoding
    tag = soup.find('meta', {'http-equiv': 'Content-Type'})
    enc = re.search('charset=([\-\w]+)[; ]?', tag.get('content')).group(1) if tag else 'utf-8'

    # get interesting images/links
    tags = soup.find_all('img')
    img_list = list(set(t.get('src') for t in tags if t.get('src')))
    tags = soup.find_all('link')
    link_list = list(set(
        (t.get('href', ''), t.get('type', '')) for t in tags if t.get('type')
    ))

    # add main MHTML header
    t = time.time()
    lt = time.localtime(t)
    timestamp = time.ctime(time.mktime(lt))
    boundary = "----=_NextPart_%s" % time.strftime("%Y%m%d_%H%M%S", lt)
    out = add_header(q_encode(title, enc), timestamp, boundary)

    # add main file
    content_type = 'text/html; charset="%s"' % enc
    out += add_part('quoted-printable', boundary, content_type, url, main_page)

    # add image links
    for img_url in img_list:
        # ensure the url is absolute
        img_url = urllib.parse.urljoin(url, img_url)
        # get image file
        (res, img_contents) = get_html_url(vals, img_url)
        if res < 0:
            print("Error on %s: %s" % (img_url, as_str(img_contents)))
            continue
        # get mime type
        mime_type, _ = guess_type(img_url)
        if mime_type is None:
            mime_type = ext2mime(imghdr.what(BytesIO(img_contents)))
        if mime_type is None:
            mime_type = 'application/octet-stream'
        # append image header
        out += add_part('base64', boundary, mime_type, img_url, img_contents)

    # add other links
    for link_url, mime_type in link_list:
        # ensure the url is absolute
        link_url = urllib.parse.urljoin(url, link_url)
        # get url file
        (res, link_contents) = get_html_url(vals, link_url)
        if res < 0:
            print("Error on %s: %s" % (link_url, as_str(link_contents)))
            continue
        if mime_type in vals['base64_mime_types']:
            # append link as base 64
            out += add_part('base64', boundary, mime_type, link_url, link_contents)
        elif mime_type in vals['qp_mime_types']:
            # append link as quoted-printable
            out += add_part('quoted-printable', boundary, mime_type, link_url, link_contents)
        elif mime_type in vals['ignore_mime_types']:
            continue
        else:
            print("Unknown mime type: \"%s\"" % mime_type)
            sys.exit(-1)

    # finish mht file
    out += "\n--%s--\n" % boundary
    return 0, out


def parse_part(part):
    part = part.strip()
    # parse the part description (first three lines)
    # get Content-Type
    pat1 = 'Content-Type: (.*)'
    pat1_res = re.search(pat1, part, re.I)
    ctype = pat1_res.groups()[0].strip() if pat1_res else ''
    # get Content-Transfer-Encoding
    pat2 = 'Content-Transfer-Encoding: (.*)'
    pat2_res = re.search(pat2, part, re.I)
    cenc = pat2_res.groups()[0].strip() if pat2_res else ''
    # get Content-Location
    pat3 = 'Content-Location: (.*)'
    pat3_res = re.search(pat3, part, re.I)
    cloc = pat3_res.groups()[0].strip() if pat3_res else ''
    # check part description
    if cenc == '':
        return -1, ctype, cenc, cloc, ''
    # parse the contents
    try:
        contents = part.split('\n\n', 1)[1]
    except:
        contents = part.split('\n\r\n', 1)[1]
    if cenc == 'base64':
        s = base64.b64decode(contents)
    elif cenc == 'quoted-printable':
        s = quopri.decodestring(contents)
    return 0, ctype, cenc, cloc, s
    

def parse_file(vals, contents):
    # get boundary
    bnd_pat = 'boundary *= *" *([^"]*) *'
    bnd_res = re.search(bnd_pat, contents, re.I)
    bnd = bnd_res.groups()[0] if bnd_res else ''
    if bnd == '':
        return -1, 'no boundary'

    # split using the boundary
    parts = contents.split('--' + bnd)

    # parse the parts
    out = []
    for i, part in enumerate(parts):
        (res, ctype, cenc, cloc, s) = parse_part(part)
        if res == -1:
            continue
        out.append([ctype, cenc, cloc, s])

    if vals['debug'] > 1:
        print("%i parts" % len(out))
    return 0, out


# \brief Get an URL as HTML
#
# \param[in] url URL to get
# \retval (error code, contents|error message)
def get_html(url):
    # use default vals
    vals = copy.deepcopy(default)
    return get_html_url(vals, url)


# \brief Get an URL and MHTML'ize it
#
# \param[in] url URL to get
# \retval (error code, contents|error message)
# \sa get_url()
def get(url):
    # use default vals
    vals = copy.deepcopy(default)
    return get_url(vals, url)


# \brief Get an MHTML file and convert it into different files
#
# \param[in] contents MHTML file contents
# \retval (error code, file array|error message)
def parse(contents):
    # use default vals
    vals = copy.deepcopy(default)
    return parse_file(vals, contents)


def usage(argv):
    global default
    print("usage: %s [opts] <url|file> <dst>" % (argv[0]))
    print("where opts can be:")
    print("\t-g: get url and mhtmlize it [default]")
    print("\t-p: parse mhtml file")
    print("\t-d: increase the debug info [default=%s]" % default['debug'])
    print("\t-h: help info")


# \brief Parse CLI options
def get_opts(argv):
    global default

    # options
    opt_short = "hdp"
    opt_long = ["help", "debug", "parse"]

    # default values
    values = copy.deepcopy(default)

    # start parsing
    try:
        opts, args = getopt.getopt(argv[1:], opt_short, opt_long)
    except getopt.GetoptError:
        usage(argv)
        sys.exit(2)

    # parse arguments
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage(argv)
            sys.exit()
        elif opt in ("-d", "--debug"):
            values['debug'] += 1
        elif opt in ("-g", "--get"):
            values['operation'] = 'get'
        elif opt in ("-p", "--parse"):
            values['operation'] = 'parse'
        #elif opt in ("-g", "--grammar"): values['grammar'] = arg

    remaining = args
    return values, remaining


def main(argv):
    # parse options
    (vals, remaining) = get_opts(argv)
    if vals['debug'] > 1:
        for k, v in vals.items():
            print("vals['%s'] = %s" % (k, v))
        print("remaining args is %s" % remaining)
    # check number of remaining arguments
    if len(remaining) < 1 or len(remaining) > 2:
        usage(argv)
        sys.exit(2)

    # get url into MHTML file
    if vals['operation'] == 'get':
        url = remaining[0]
        (res, out) = get_url(vals, url)
        if res < 0:
            print(out)
            print('----Error!')
            sys.exit(-1)
        if len(remaining) == 2:
            outfile = remaining[1]
            with open(outfile, 'w') as f:
                f.write(out)
            if vals['debug'] > 0:
                print("output in %s" % outfile)

    # parse MHTML file into its components
    elif vals['operation'] == 'parse':
        filename = remaining[0]
        try:
            with open(filename, "r") as f:
                contents = f.read()
        except:
            # error reading file
            print("Error reading file %s" % filename)
            sys.exit(-1)
        (res, out) = parse_file(vals, contents)
        if res < 0:
            print(out)
            print('----Error!')
            sys.exit(-1)
        if len(remaining) == 2:
            outdir = remaining[1]
            # dump contents
            for i in range(len(out)):
                urlname = out[i][2]
                contents = out[i][3]
                filename = os.path.basename(urllib.parse.urlsplit(urlname)[2])
                if filename == '':
                    filename = 'index.html'
                filename = os.path.join(outdir, filename)
                with open(filename, 'w') as f:
                    f.write(contents)
                if vals['debug'] > 0:
                    print("output in %s" % filename)
    

if __name__ == "__main__":
    def test_get():
        url = 'http://www.reddit.com/r/news/comments/2qjeot/twenty_states_will_raise_their_minimum_wage_on/'
        (res, out) = get_url(default, url)
        if res < 0:
            print(out)
            print('----Error!')
            sys.exit(-1)
        outfile = 'reddittest.mht'
        with open(outfile, 'w') as f:
            f.write(out)

    def test_parse():
        filename = 'reddittest.mht'
        vals = default
        vals['operation'] = 'parse'
        try:
            with open(filename, "r") as f:
                contents = f.read()
        except:
            # error reading file
            print("Error reading file %s" % filename)
            sys.exit(-1)
        (res, out) = parse_file(vals, contents)
        if res < 0:
            print(out)
            print('----Error!')
            sys.exit(-1)
        outdir = 'reddittest'
        try:
            os.mkdir(outdir)
        except OSError:
            pass
        # dump contents
        for i in range(len(out)):
            urlname = out[i][2]
            contents = out[i][3]
            filename = os.path.basename(urllib.parse.urlsplit(urlname)[2])
            if filename == '':
                filename = 'index.html'
            if '.' not in filename and 'text/html' in out[i][0]:
                filename += '.html'
            filename = os.path.join(outdir, filename)
            with open(filename, 'wb') as f:
                f.write(as_bytes(contents))
            if vals['debug'] > 0:
                print("output in %s" % filename)

    main(sys.argv)