try:  # importing from inside the package
    import scheme
    from scheme import Message
    from config import *
    from readable_scheme import ReadableScheme
    from connection import SerialConnection, FileReaderConnection, FileWriterConnection, UDPConnection
    from board import IMUBoard
    from collector import Collector, SessionStatistics, RealTimePlot
except ModuleNotFoundError:  # importing from outside of the package
    import tools.scheme
    from tools.scheme import Message
    from tools.config import *
    from tools.readable_scheme import ReadableScheme
    from tools.connection import SerialConnection, FileReaderConnection, FileWriterConnection, UDPConnection
    from tools.board import IMUBoard
    from tools.collector import Collector, SessionStatistics, RealTimePlot
