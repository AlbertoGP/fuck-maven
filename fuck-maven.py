#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# `fuck-maven.py` locates the dependencies listed in pom.xml files and
# can **download** the **JAR** files, create a **Manifest.txt** file, and/or
# create a **build.xml** file.
#
# Author: Alberto González Palomo http://matracas.org
# ©2016 Alberto González Palomo http://matracas.org
# Created: 2016-11-10
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program. If not, see <http://www.gnu.org/licenses/>.

from xml.etree.ElementTree import *
import urllib.request, urllib.error
import re, os, os.path, errno, getopt, sys

outputDir = './lib'
manifest = False
buildxml = False
listOnly = False
transitive = False
cache = './cache' # cache directory name, or empty string / False.
scopes = ['compile','runtime'] # compile|runtime|test|provided|system
streamBufferSize = 8192 # bytes

def display_help():
    print(r'''Usage: pythonpp [options] pom.xml [pom2.xml]...
Downloads the dependencies listed in pom.xml v4.0.0 files.
Note: if the pom.xml file references a parent it will be ignored,
      but you can give that parent pom.xml as another argument in front.

  -h, --help          Display this message.
  -o, --output=dir    Output directory for the downloaded JARs.
                    = "{}"
  -m, --manifest      Write Manifest.txt in the current directory.
                    = {}
  -b, --buildxml      Write build.xml in the current directory.
                      This is a custom build file that will take any JARs
                      from "{}" and package them automatically with the
                      compiled program in a ready-to-use single "fat JAR".
                    = {}
  -l, --list          Do not download the JARs, just list them.
                    = {}
  -t, --transitive    Fetch transitive (a.k.a. recursive) dependencies.
                    = {}
  -c, --cache=dir     Cache POM and metadata files in the given directory.
                      An empty string means no caching.
                    = "{}"
  -s, --scopes=a,b,c  Only fetch dependencies in the given scopes.
                      See https://maven.apache.org/pom.html#Dependencies
                    = "{}"
'''.format(outputDir, manifest, outputDir, buildxml, listOnly,
           transitive, cache, ','.join(scopes)), file=sys.stderr)

try:
    opts, args = getopt.getopt(sys.argv[1:],
                               'ho:mbltc:s:',
                               ('help',
                                'output=', 'manifest', 'buildxml', 'list',
                                'transitive', 'cache=', 'scopes=',
                               ))
except(getopt.error, problem):
    print('Command line option problem: ', problem, '\n', file=sys.stderr)
    display_help()
    exit(1)

for o, a in opts:
    if (o == '-o')|(o == '--output'):     outputDir = a
    if (o == '-m')|(o == '--manifest'):   manifest = True
    if (o == '-b')|(o == '--buildxml'):   buildxml = True
    if (o == '-l')|(o == '--list'):       listOnly = True
    if (o == '-t')|(o == '--transitive'): transitive = True
    if (o == '-c')|(o == '--cache'):      cache = a
    if (o == '-s')|(o == '--scopes'):     scopes = a.split(',')
    if (o == '-h')|(o == '--help'):
        display_help()
        exit(0)

if len(args) < 1:
    print('You must specify at least one POM file.', file=sys.stderr)
    display_help()
    exit(1)

failedUrls = []
transitiveChain = []

ns = {
    'mvn': 'http://maven.apache.org/POM/4.0.0'
}

trailingSlashes = re.compile('/*$')
def ensureTrailingSlash(path): return trailingSlashes.sub('/', path)


def itemUrl(repoUrl, item, type=''):
    url = [repoUrl + item['pathName']]
    if 'maven-metadata' == type:
        url.append('maven-metadata.xml')
    else:
        url.append(item['version'])
        if type: url.append(item['fileName'][:-len(item['type'])] + type)
        else:    url.append(item['fileName'])
    return '/'.join(url)

def updateFileName(item):
    item['fileName'] = item['artifactId']
    if not item['version'] is None: item['fileName'] += '-' + item['version']
    item['fileName'] += '.' + item['type']

def mkdirp(path):
    try: os.makedirs(path)
    except OSError as e:
        if errno.EEXIST != e.errno:      raise
        if not os.path.isdir(outputDir): raise


rePropertyMacro = re.compile(r'\$\{([a-zA-Z0-9.]+)\}')
def expand(value, properties):
    return rePropertyMacro.sub(lambda m:
                               properties[m.group(1)]
                               if   m.group(1) in properties
                               else m.group(0),
                               value)

def evaluate(x, properties):
    if isinstance(x, list):
        return map(lambda x: expand(x.text, properties) if x is not None else x,
                   x)
    else:
        return expand(x.text, properties) if x is not None else x

reNamespace = re.compile(r'\{[^}]*\}|[^:]*:')
def localName(element):
    return reNamespace.sub('', element.tag)

urlHostRe = re.compile(r'^https?://[^/]+')
def httpGet(url):
    global urlHostRe
    res = False
    code = 0
    fileName = False
    if cache:
        fileName = cache + urlHostRe.sub('', url)
        if os.path.lexists(fileName):
            res = open(fileName)
            code = 200
            fileName = False
    if not res:
        res = urllib.request.urlopen(url)
        code = res.getcode()
    content = res.read() # No streaming, this function is meant for small files.
    if cache and fileName:
        mkdirp(os.path.dirname(fileName))
        with open(fileName, 'wb') as out: out.write(content)
    return (code, content)

def collect_dependencies(pom, dependencies, parentRepositories=[]):
    global failedUrls, ns, trailingSlashes, transitiveChain
    indent = ' ' * len(transitiveChain)
    try:
        if 'project' == pom.tag:
            print(indent + 'ERROR: mishaped POM file lacks namespace,',
                  file=sys.stderr)
            print(indent + '       monkey-patching the Maven namespace!',
                  file=sys.stderr)
            for element in pom.iter():
                element.tag = '{' + ns['mvn'] + '}' + element.tag
        properties = {}
        for name in ['groupId', 'artifactId', 'name', 'version',
                     'packaging', 'description', 'inceptionYear']:
            value = evaluate(pom.find('./mvn:' + name, ns), properties)
            if not value is None: properties['project.' + name] = value
        for property in pom.findall('./mvn:properties/*', ns):
            # TODO: recursive expansion
            properties[localName(property)] = evaluate(property, properties)
        uniqueKey = evaluate(pom.find('./mvn:groupId', ns), properties)
        if uniqueKey is None: uniqueKey = ''
        else:                 uniqueKey = uniqueKey + ':'
        uniqueKey += evaluate(pom.find('./mvn:artifactId', ns), properties)
        if uniqueKey in transitiveChain:
            print(indent + 'ERROR: dependency cycle:',
                  ' → '.join(transitiveChain), '→', uniqueKey,
                  file=sys.stderr)
            return
        transitiveChain.append(uniqueKey)
    except Exception as e:
        print(indent +
              'ERROR: wrong format in POM file, no mvn:artifactId element.', e,
              file=sys.stderr)
        return
    print(' → '.join(transitiveChain))
    repositories = []
    for repository in pom.findall('./mvn:repositories/mvn:repository', ns):
        id  = evaluate(repository.find('mvn:id',  ns), properties)
        url = evaluate(repository.find('mvn:url', ns), properties)
        if url is None:
            print(indent + 'ERROR: no url in repository',
                  tostring(repository, encoding='unicode'),
                  file=sys.stderr)
        else:
            if id is None:
                print(indent + 'ERROR: no url in repository',
                      tostring(repository, encoding='unicode'),
                      file=sys.stderr)
            else:
                # The maven2/ path fragment is defined in Maven's default POM:
                # https://maven.apache.org/guides/introduction/introduction-to-the-pom.html
                if 'central' == id: url = 'http://repo1.maven.org/maven2'
                url = ensureTrailingSlash(url)
                if not url in repositories: repositories.append(url)

    for url in repositories: print(indent + 'Repo:', url)
    repositories.extend(parentRepositories)

    for dependency in pom.findall('./mvn:dependencies/mvn:dependency', ns):
        scope      = evaluate(dependency.find('mvn:scope',      ns), properties)
        if scope is None: scope = 'compile'
        if not scope in scopes: continue

        groupId    = evaluate(dependency.find('mvn:groupId',    ns), properties)
        artifactId = evaluate(dependency.find('mvn:artifactId', ns), properties)
        version    = evaluate(dependency.find('mvn:version',    ns), properties)
        type       = evaluate(dependency.find('mvn:type',       ns), properties)
        pathName = ''
        if groupId is None: pathName = False
        else:
            pathName += ensureTrailingSlash(groupId.replace('.', '/'))
            if artifactId is None: pathName = False
            else:
                pathName += artifactId
                if type is None: type = 'jar'
                if rePropertyMacro.search(groupId):
                    print(indent + 'ERROR: unresolved groupId', groupId,
                          file=sys.stderr)
                    continue
                if rePropertyMacro.search(artifactId):
                    print(indent + 'ERROR: unresolved artifactId', artifactId,
                          file=sys.stderr)
                    continue
        if not pathName:
            print(indent + 'ERROR: incorrect dependency specification:',
                  'groupId:', groupId, 'artifactId:', artifactId,
                  tostring(dependency, encoding='unicode'),
                  file=sys.stderr)
            continue

        item = {
            'repositories': repositories[:],
            'pathName': pathName,
            'fileName': '',
            'groupId':    groupId,
            'artifactId': artifactId,
            'version':    version,
            'type':       type
        }
        updateFileName(item)

        dependencyKey = item['pathName'] + '/' + item['fileName']
        if dependencyKey in dependencies: continue
        code = 0
        localFailedUrls = []
        for repoUrl in repositories:
            url = ''
            xml = ''
            try:
                if version is None:
                    # TODO: support version ranges:
                    # http://stackoverflow.com/a/1172371/291462
                    url = itemUrl(repoUrl, item, 'maven-metadata')
                    code, xml = httpGet(url)
                    tree = XML(xml)
                    print(indent + str(code), item['artifactId'], 'Metadata')
                    version = tree.find('./versioning/latest', ns)
                    if version is None:
                        version = tree.find('./versioning/versions/version', ns)
                    if version is None:
                        raise ParseError('No versioning information in ' + url)
                    item['version'] = version.text
                    item['repositories'] = [repoUrl]
                    updateFileName(item)
                dependencies[dependencyKey] = item
                localFailedUrls = []
                if transitive:
                    url = itemUrl(repoUrl, item, 'pom')
                    code, xml = httpGet(url)
                    collect_dependencies(XML(xml), dependencies, repositories)
                break
            except urllib.error.HTTPError as e: code = e.code
            except urllib.error.URLError  as e: code = 0
            except ParseError as e:
                print(indent + 'ERROR', e, file=sys.stderr)
                print(indent + url, file=sys.stderr)
                print(indent + xml.decode('UTF-8'), file=sys.stderr)
            localFailedUrls.append(str(code) + ' ' + url)
        failedUrls.extend(localFailedUrls)
    transitiveChain.pop()


def download(dependencies, outputDir):
    global failedUrls, listOnly
    for item in dependencies.values():
        fullFileName = ensureTrailingSlash(outputDir) + item['fileName']
        if os.path.lexists(fullFileName):
            print('Already downloaded', fullFileName)
            continue

        localFailedUrls = []
        for repoUrl in item['repositories']:
            fileUrl = itemUrl(repoUrl, item)
            try:
                req = urllib.request.Request(
                    url    = fileUrl,
                    method = 'HEAD' if listOnly else 'GET'
                )
                res = urllib.request.urlopen(req)
                code = res.getcode()
            except urllib.error.HTTPError as e: code = e.code
            except urllib.error.URLError  as e: code = e.code
            if 200 != code: localFailedUrls.append(str(code) + ' ' + fileUrl)
            else:
                localFailedUrls = []
                print(fileUrl)
                if listOnly: break
                mkdirp(outputDir)
                with open(fullFileName, 'wb') as out:
                    eof = False
                    while not eof: # r/w in blocks to handle big files.
                        data = res.read(streamBufferSize)
                        if data: out.write(data)
                        else:    eof = True
                break
        failedUrls.extend(localFailedUrls)


def expandEntities(xmlText, context):
    global project
    return re.compile(r'&([a-zA-Z]+);').sub(
        lambda x: project[x.group(1)] or x.group(0), xmlText
    )

project = {
    'name': '', 'fullname': '', 'description': '',
    'source': '', 'target': '',
    'mainClass': '',
    'lib': outputDir
}

buildxmlTemplate = '''<project name="&name;" default="dist" basedir=".">
  <!-- This build.xml file was initially created by Alberto González Palomo.
       It got me a Necromancer badge in Stack Overflow: http://stackoverflow.com/a/2426245
       For questions or bug reports write to bugs@sentido-labs.com -->
  <property name="project.fullname" value="&fullname;"/>
  <description>
    &description;
  </description>
  <!-- set global properties for this build -->
  <property name="src"   location="src"/>
  <property name="lib"   location="&lib;"/>
  <property name="build" location="build"/>
  <property name="dist"  location="dist"/>
  <property name="docs"  location="docs"/>

  <target name="init">
    <!-- Create the time stamp -->
    <tstamp/>
    <!-- Create the build directory structure used by compile -->
    <mkdir dir="${build}"/>
  </target>

  <path id="compile.classpath">
    <pathelement path="${classpath}"/>
    <fileset dir="${lib}">
      <include name="**/*.jar"/>
    </fileset>
  </path>

  <target name="compile" depends="init"
          description="compile the source">
    <!-- Compile the java code from ${src} into ${build} -->
    <javac debug="on" srcdir="${src}" destdir="${build}" encoding="UTF-8" includeantruntime="false">
      <!-- compilerarg value="-Xlint"/ -->
      <classpath refid="compile.classpath"/>
    </javac>
  </target>

  <target name="dist" depends="compile"
          description="generate the distribution" >
    <!-- Create the distribution directory -->
    <mkdir dir="${dist}/lib"/>

    <!-- Put everything in ${build} into the ${ant.project.name}-${DSTAMP}.jar file -->
    <jar jarfile="${dist}/${ant.project.name}-${DSTAMP}.jar" manifest="Manifest.txt" filesetmanifest="mergewithoutmain">
      <fileset dir="${build}" includes="**/*.*"/>
      <zipgroupfileset dir="${lib}" includes="**/*.jar"/>
      <fileset dir="." includes="README"/>
    </jar>
    <copy file="${dist}/${ant.project.name}-${DSTAMP}.jar" tofile="${dist}/${ant.project.name}.jar"/>

    <jar jarfile="${dist}/lib/${ant.project.name}-${DSTAMP}.jar" manifest="Manifest.txt" filesetmanifest="mergewithoutmain">
      <fileset dir="${build}" includes="**/*.*" excludes="examples"/>
      <fileset dir="." includes="README"/>
    </jar>
    <copy file="${dist}/lib/${ant.project.name}-${DSTAMP}.jar" tofile="${dist}/lib/${ant.project.name}.jar"/>
  </target>

  <target name="docs" depends="init"
          description="generate the documentation" >
    <mkdir dir="${docs}"/>
    <copy todir="${docs}"><fileset dir="doc-assets"/></copy>
    <!-- Extract the documentation from ${src} into ${docs} -->
    <javadoc sourcepath="${src}" encoding="UTF-8" charset="UTF-8" overview="${src}/overview.html" windowtitle="${project.fullname}" author="true" version="true" use="true" destdir="${docs}" excludepackagenames="">
      <classpath refid="compile.classpath"/>
      <link href="http://docs.oracle.com/javase/7/docs/api/"/>
      <link href="https://xmlgraphics.apache.org/batik/javadoc/"/>
    </javadoc>
  </target>

  <target name="clean"
          description="clean up" >
    <!-- Delete the ${build} and ${dist} directory trees -->
    <delete dir="${build}"/>
    <delete dir="${dist}"/>
    <delete dir="${docs}"/>
  </target>
</project>
'''

for inputFile in args:
    pom = parse(inputFile).getroot()
    node = pom.find('./mvn:build/mvn:plugins/mvn:plugin[mvn:artifactId="exec-maven-plugin"]/mvn:configuration/mvn:mainClass', ns)
    if node is not None:
        print('Main-Class: ' + node.text)
        project['mainClass'] = node.text
        dependencies = {}
    node = pom.find('./mvn:name', ns)
    if node is not None:
        project['name'] = node.text
    project['fullname'] = project['name']
    node = pom.find('./mvn:organization/mvn:name', ns)
    if node is not None:
        project['fullname'] = node.text + ' ' + project['fullname']
    node = pom.find('./mvn:organization/mvn:url', ns)
    if node is not None:
        project['fullname'] += ' ' + node.text
    node = pom.find('./mvn:description', ns)
    if node is not None:
        project['description'] = node.text
    print('Collecting dependencies...')
    collect_dependencies(pom, dependencies)
for item in dependencies.values(): print('-', item['fileName'])
if not listOnly: print('Downloading dependencies to:', outputDir, '\n')
download(dependencies, outputDir)
if len(failedUrls) > 0:
    for message in failedUrls: print('Error:', message, file=sys.stderr)
if manifest:
    with open('Manifest.txt', 'wb') as out:
        out.write(('Main-Class: ' + project['mainClass'] + '\n').encode());
if buildxml:
    with open('build.xml', 'wb') as out:
        out.write(expandEntities(buildxmlTemplate, project).encode())
