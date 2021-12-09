try:  # importing from inside the package
    import message_scheme
    from message_scheme import Message
    from config import *
    from readable_scheme import ReadableScheme, int_to_ascii, ascii_to_int
    from connection import SerialConnection, FileReaderConnection, FileWriterConnection, UDPConnection
    from board import IMUBoard
    from collector import Collector, SessionStatistics, RealTimePlot
except ModuleNotFoundError:  # importing from outside of the package
    import tools.message_scheme
    from tools.message_scheme import Message
    from tools.config import *
    from tools.readable_scheme import ReadableScheme, int_to_ascii, ascii_to_int
    from tools.connection import SerialConnection, FileReaderConnection, FileWriterConnection, UDPConnection
    from tools.board import IMUBoard
    from tools.collector import Collector, SessionStatistics, RealTimePlot
