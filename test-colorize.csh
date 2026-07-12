#!/bin/csh -f

# colorize.py --help | colorize.py --color '#2BF9FA' --find "[\[ /]+(-|--)[A-Za-z\]-]+" | aha --black > ! colorize-help.html

foreach prog (*.py) 
  ${prog} --help | colorize.py --color '#2BF9FA' --find "[\[ /]+(-|--)[A-Za-z\]-]+" | aha --black > ! ${prog:r}-help.html
end