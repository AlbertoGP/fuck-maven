`fuck-maven.py` locates the dependencies listed in pom.xml files and
can **download** the **JAR** files, create a **Manifest.txt** file, and/or
create a **build.xml** file. See [Usage](#usage) below.

Some times I just want to take a quick look at some program that uses
[Apache Maven](https://maven.apache.org/)
without having to install it and debug the POM file.

It has worked well enough for that so far.

It has **limited support** for reading `pom.xml` files:
for instance, only specific dependency versions are allowed,
not things like version ranges.
In exchange, it is less strict about broken POM files.

I chose **Python 3** because it is already installed in most of the computers
I use, and if not it is a simpler installation than with Java.
The computer where I donwload the files is not always the one
where I will compile the Java program.

There are **other ways** of retrieving the JARs from a `pom.xml` file:
- [How to download jars from Maven Central](http://halyph.com/blog/2015/03/17/how-to-download-jars-from-maven-central.html)
- [Apache Maven](https://maven.apache.org/) method: [Using Maven to download dependencies to a directory on the command line](http://stackoverflow.com/questions/15450383/using-maven-to-download-dependencies-to-a-directory-on-the-command-line/15456621)
- [Apache Ivy](https://ant.apache.org/ivy/) method: [Simplest Ivy code to programmatically retrieve dependency from Maven Central](http://stackoverflow.com/questions/15598612/simplest-ivy-code-to-programmatically-retrieve-dependency-from-maven-central)

I tried to use Ivy but it failed when it could not retrieve the *"parent"*
configured in the POM file.

Whether it is the faulf of the POM file author (likely), or Maven's, or Ivy's,
I just do not have time for that; thus `fuck-maven.py`.

## License
GPLv3, GNU General Public License version 3.

## Requirements
- Python 3

## Usage
```
Usage: pythonpp [options] pom.xml [pom2.xml]...
Downloads the dependencies listed in pom.xml v4.0.0 files.
Note: if the pom.xml file references a parent it will be ignored,
      but you can give that parent pom.xml as another argument in front.

  -h, --help          Display this message.
  -o, --output=dir    Output directory for the downloaded JARs.
                    = "./lib"
  -m, --manifest      Write Manifest.txt in the current directory.
                    = False
  -b, --buildxml      Write build.xml in the current directory.
                      This is a custom build file that will take any JARs
                      from "./lib" and package them automatically with the
                      compiled program in a ready-to-use single "fat JAR".
                    = False
  -l, --list          Do not download the JARs, just list them.
                    = False
  -t, --transitive    Fetch transitive (a.k.a. recursive) dependencies.
                    = False
  -c, --cache=dir     Cache POM and metadata files in the given directory.
                      An empty string means no caching.
                    = "./cache"
  -s, --scopes=a,b,c  Only fetch dependencies in the given scopes.
                      See https://maven.apache.org/pom.html#Dependencies
                    = "compile,runtime"
```
