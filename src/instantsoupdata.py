#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import uuid

from construct import Container, Enum, PrefixedArray, Struct, ULInt32
from construct import ULInt16, ULInt8, OptionalGreedyRange, PascalString
from construct import CString, Switch, GreedyRange
from PyQt4 import QtCore, QtNetwork
from functools import partial
from collections import defaultdict

log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)

group_address = QtNetwork.QHostAddress("239.255.99.63")
broadcast_port = 55555
server_start_port = 49190


class InstantSoupData(object):

    # common
    server = Struct("server",
                 CString("server_id"),
                 PrefixedArray(CString('channels'),
                     ULInt8("num_channels")
                 )
             )

    # structures from rfc
    opt_client_nick = CString('nickname')

    opt_client_membership = PrefixedArray(server,
                                 ULInt8("num_servers")
                             )

    opt_server = Struct("opt_server",
                     ULInt16("port")
                 )

    opt_server_channels = Struct("opt_server_channels",
                             PrefixedArray(CString("channels"),
                                 ULInt8("num_channels"))
                          )

    opt_server_invite = Struct("opt_server_invite",
                             CString("channel_id"),
                             PrefixedArray(CString("client_id"),
                                 ULInt8("num_clients")
                             )
                         )

    # option fields
    option = Struct("option",
                 Enum(ULInt8("option_id"),
                     CLIENT_NICK_OPTION=0x01,
                     CLIENT_MEMBERSHIP_OPTION=0x02,
                     SERVER_OPTION=0x10,
                     SERVER_CHANNELS_OPTION=0x11,
                     SERVER_INVITE_OPTION=0x12
                 ),
                 Switch("option_data",
                     lambda ctx: ctx["option_id"],
                     {
                     "CLIENT_NICK_OPTION": opt_client_nick,
                     "CLIENT_MEMBERSHIP_OPTION": opt_client_membership,
                     "SERVER_OPTION": opt_server,
                     "SERVER_CHANNELS_OPTION": opt_server_channels,
                     "SERVER_INVITE_OPTION": opt_server_invite
                     }
                 )
             )

    # the peer pdu itself
    peer_pdu = Struct("peer_pdu",
                   CString('id'),
                   OptionalGreedyRange(option)
               )

    command = PascalString("command", length_field=ULInt32("length"))


class Client(QtCore.QObject):
    DEFAULT_WAITING_TIME = 1000

    REGULAR_PDU_WAITING_TIME = 15000

    # emitted when a new client is discovered
    new_client = QtCore.pyqtSignal()

    # emitted when a nick of a client is changed
    client_nick_change = QtCore.pyqtSignal()

    # emitted when a new server is discovered
    new_server = QtCore.pyqtSignal(str)

    # emitted when a other client joins or leaves a channel
    client_membership_changed = QtCore.pyqtSignal()

    # emitted when a client received a message from a server, for testing purposes
    message_received = QtCore.pyqtSignal(str)

    def __init__(self, nickname="Telematik", parent=None):
        QtCore.QObject.__init__(self, parent)

        self.id = str(uuid.uuid1())
        self.nickname = nickname
        self.pdu_number = 0

        self.sreate_udp_socket()

        # mapping from client.id to nickname
        self.lobby_users = {}

        # mapping from (server_id, channel) to a tuple containing (address, port, tcp_socket)
        self.servers = {}

        # mapping from server_id to channel_id to a list of client_ids
        # stores the membership of OTHER peers
        self.channel_membership = defaultdict(lambda: defaultdict(set))

        self.send_client_nick()

        # setup the regular_pdu_timer for the regular pdu
        self.regular_pdu_timer = QtCore.QTimer()
        self.regular_pdu_timer.timeout.connect(self.send_regular_pdu)
        self.regular_pdu_timer.start(self.REGULAR_PDU_WAITING_TIME)

    #
    # SOCKET FUNCTIONS
    #
    # create a socket for the PDUs
    def sreate_udp_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket()
        self.udp_socket.bind(broadcast_port,
                             QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)

        # connect the socket input with the processing function
        self.udp_socket.readyRead.connect(self.process_pending_datagrams)

    # create a socket for a channel
    def create_tcp_socket(self, address, port):
        socket = QtNetwork.QTcpSocket()

        # we have a port, connect!
        socket.connectToHost(address, port)

        if not socket.waitForConnected(self.DEFAULT_WAITING_TIME):
            raise Exception('no connection for address %s:%s' %
                      (address.toString(), port))

        # connect with processing function
        socket.readyRead.connect(partial(self.read_from_tcp_socket, socket))

        return socket

    def read_from_tcp_socket(self, socket):
        data = socket.readAll()
        peer_pdu = InstantSoupData.peer_pdu.parse(data)
        # uid = peer_pdu["id"]
        for option in peer_pdu["option"]:
            if option["option_id"] == "SERVER_INVITE_OPTION":
                # TODO handle server invite option here
                pass

    #
    # SERVER COMMANDOS
    #
    def command_join(self, channel_name, server_id):
        self.send_command_to_server("JOIN\x00%s" % channel_name, server_id)
        self.send_client_membership_option((server_id, channel_name))

    def command_say(self, text, channel_name, server_id):
        self.send_command_to_server("SAY\x00%s" % text,
                                    channel_name, server_id)

    def command_standby(self, peer_id, channel_name, server_id):
        self.send_command_to_server("STANDBY\x00%s" % peer_id,
                                    channel_name, server_id)

    def command_exit(self, channel_name, server_id):
        self.send_command_to_server("EXIT", channel_name, server_id)

    def send_command_to_server(self, command, server_id, channel=None):
        if (server_id, channel) not in self.servers:
            print "server id", server_id
            log.error("trying to connect to server %s which doesn't exist or" +
                      "hasn't yet been recognized" % server_id)
            return

        # we are already connected!
        (_, _, socket) = self.servers[(server_id, channel)]
        socket.write(InstantSoupData.command.build(command))
        socket.waitForBytesWritten(self.DEFAULT_WAITING_TIME)

    #
    # DATAGRAMS
    #
    def send_regular_pdu(self):

        # send nickname
        self.send_client_nick()

        # sent the option with every fourth pdu (see rfc)
        if self.pdu_number % 4 == 0:
            self.send_client_membership_option()

        self.pdu_number += 1

    def send_client_nick(self):

        # define the data to send & send
        option_data = self.nickname

        option = Container(option_id="CLIENT_NICK_OPTION",
                     option_data=option_data
                 )

        pdu = Container(id=self.id,
                  option=[option]
              )

        data = InstantSoupData.peer_pdu.build(pdu)
        self._send_datagram(data)

        log.debug('PDU: CLIENT_NICK_OPTION - ID: %i - SENT' % self.pdu_number)

    def send_client_membership_option(self, new_channel=None):

        # mapping from server_id to a list of channel_ids
        server_channels = defaultdict(list)
        for (server_id, channel_id) in self.servers.keys():
            if channel_id:
                server_channels[server_id].append(channel_id)

        # if we have a new channel, broadcast it
        if new_channel:
            server_id, channel_id = new_channel
            server_channels[server_id].append(channel_id)

        # build the channel list for a server
        option_data = []
        for server_id, channels in server_channels.items():
            data = Container(server_id=server_id, channels=channels)
            option_data.append(data)

        # do we have something to send?
        if option_data:
            option = Container(option_id="CLIENT_MEMBERSHIP_OPTION",
                               option_data=option_data)
            pdu = Container(id=self.id, option=[option])
            data = InstantSoupData.peer_pdu.build(pdu)
            self._send_datagram(data)

        log.debug('PDU: CLIENT_NICK_MEMBERSHIP - ID: %i - SENT' %
                  self.pdu_number)

    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    #
    # PROCESSING FUNCTIONS (INCOMING DATA)
    #
    def process_pending_datagrams(self):
        maxlen = self.udp_socket.pendingDatagramSize()
        while self.udp_socket.hasPendingDatagrams():
            data, address, port = self.udp_socket.readDatagram(maxlen)
            packet = InstantSoupData.peer_pdu.parse(data)
            peer_uid = packet["id"]
            for option in packet["option"]:

                if option["option_id"] == "CLIENT_NICK_OPTION":
                    self.handle_client_nick_option(peer_uid, option)
                elif option["option_id"] == "CLIENT_MEMBERSHIP_OPTION":
                    self.handle_client_membership_option(peer_uid, option)
                elif option["option_id"] == "SERVER_OPTION":
                    self.handle_server_option(peer_uid, option, address)
                elif option["option_id"] == "SERVER_CHANNELS_OPTION":
                    self.handle_server_channels_option(peer_uid, option)
                elif option["option_id"] == "SERVER_INVITE_OPTION":
                    self.handle_server_invite_option(peer_uid, option)

    def handle_client_nick_option(self, peer_uid, option):

        # new client found or client nick was changed
        if peer_uid in self.lobby_users:

            # user already exists
            if self.lobby_users[peer_uid] != option["option_data"]:
                self.lobby_users[peer_uid] = option["option_data"]

                # SIGNAL: client nick was changed
                self.client_nick_change.emit()
        else:

            # add new client
            self.lobby_users[peer_uid] = option["option_data"]

            # SIGNAL: new client
            self.new_client.emit()

    def handle_client_membership_option(self, peer_uid, option):
        servers = option["option_data"]
        for server_container in servers:
            server_id = server_container["server_id"]
            channels = server_container["channels"]
            for channel in channels:
                self.channel_membership[server_id][channel].add(peer_uid)
                self.client_membership_changed.emit()

    def handle_server_option(self, peer_uid, option, address):
        if (peer_uid, None) not in self.servers:

            # add new server
            port = option["option_data"]["port"]
            try:
                socket = self.create_tcp_socket(address, port)
                self.servers[(peer_uid, None)] = (address, port, socket)

                # signal: we have a new server!
                self.new_server.emit(peer_uid)
            except Exception as error:
                log.error(error)

    def handle_server_channels_option(self, peer_uid, option):
        channels = option["option_data"]["channels"]
        for channel in channels:
            if (peer_uid, channel) not in self.servers:
                try:
                    (address, port, _) = self.servers[(peer_uid, None)]
                    socket = self.create_tcp_socket(address, port)
                    self.servers[(peer_uid, channel)] = (address, port, socket)

                    # signal: we have a new server!
                    self.new_server.emit(peer_uid)
                except Exception as error:
                    log.error(error)

    def handle_server_invite_option(self):
        pass

    # Prints the Object
    def __repr__(self):
        return "Client(%s, %s, lobby_users:%s, servers:%s)" % (self.nickname,
            self.id,
            self.lobby_users,
            self.servers)


class Server(QtCore.QObject):
    DEFAULT_WAITING_TIME = 1000

    REGULAR_PDU_WAITING_TIME = 15000

    debug_output = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        global server_start_port

        QtCore.QObject.__init__(self, parent)

        # Create a channel with a unique id
        self.id = str(uuid.uuid1())
        self.port = server_start_port
        self.pdu_number = 0
        server_start_port += 1

        self.sreate_udp_socket()
        self.tcp_server = QtNetwork.QTcpServer(self)

        # mapping from channel_id to a list of (client_id, tcp_socket)
        self.channels = {}

        # mapping from address to (client_id, nickname)
        self.lobby_users = {}

        if not self.tcp_server.listen(QtNetwork.QHostAddress.Any, self.port):
            log.error("Unable to start the server: %s." %
                self.tcp_server.errorString())

        # Hint: IP: 0.0.0.0 means ANY
        address = self.tcp_server.serverAddress().toString()
        port = self.tcp_server.serverPort()
        log.debug("Server is running with address %s and port %s" % (address,
            port))

        # do something, when we are connected
        self.tcp_server.newConnection.connect(self.handle_connection)

        # setup the regular_pdu_timer for the regular pdu
        self.regular_pdu_timer = QtCore.QTimer()
        self.regular_pdu_timer.timeout.connect(self.send_regular_pdu)
        self.regular_pdu_timer.start(self.REGULAR_PDU_WAITING_TIME)

    def handle_connection(self):
        client_connection = self.tcp_server.nextPendingConnection()
        client_connection.disconnected.connect(client_connection.deleteLater)

        if not client_connection.waitForConnected(self.DEFAULT_WAITING_TIME):
            log.error((client_connection.error(),
               client_connection.errorString()))
            return

        # if the connection is ready, read from socket
        client_connection.readyRead.connect(partial(self.read_incoming_socket,
            client_connection))
        client_connection.waitForReadyRead(self.DEFAULT_WAITING_TIME)

    def read_incoming_socket(self, client_connection):
        data = str(client_connection.readAll())
        client_connection.flush()
        self.handle_data(data, client_connection)
        client_connection.disconnected.connect(client_connection.deleteLater)

    def search_channel(self, socket):
        for channel_name, iterable in self.channels.items():
                for client_id, client_socket in iterable:
                    if client_socket == socket:
                        return client_id, channel_name
        return []

    def handle_data(self, command, socket):
        data = InstantSoupData.command.parse(command)

        if data.startswith("SAY"):
            self.handle_say_command(data, socket)
        elif data.startswith("JOIN"):
            self.handle_join_command(data, socket)
        elif data.startswith("EXIT"):
            pass

    def handle_say_command(self, data, socket):

        # send message to all connected peers in channel
        message = " ".join(data.split("\x00")[1:])

        try:
            author_id, channel_name = self.search_channel(socket)
            for (_, socket) in self.channels[channel_name]:
                command = "SAY\x00%s\x00%s\x00" % (author_id, message)
                data = InstantSoupData.command.build(command)
                socket.write(data)
                socket.waitForBytesWritten(self.DEFAULT_WAITING_TIME)
        except ValueError:
            log.error("socket was not found, make sure the socket is" +
                " associated with a channel. use the join command")

    def handle_join_command(self, data, socket):
        address = socket.peerAddress()
        channel_name = data.split("\x00")[1]

        log.debug("user %s is opening/joining a channel with name %s" %
                  (self.lobby_users[address], channel_name))
        try:
            channel_data = (self.lobby_users[address][0], socket)
            self.channels[channel_name].add(channel_data)
            log.debug("channel already exists")
        except KeyError:
            private = channel_name.startswith("@")
            log.debug("creating channel %s" % channel_name)

            # create new channel
            channel_data = (self.lobby_users[address][0], socket)
            self.channels[channel_name] = set()
            self.channels[channel_name].add(channel_data)

            if not private:
                self.send_server_channel_option()
            else:
                self.send_server_invite_option([self.lobby_users[address][0]], channel_name)

    def send_server_invite_option(self, invite_client_ids, channel_id):

        # for each client_id find the socket on which to send the server_invite option
        for invite_client_id in invite_client_ids:
            for channel_id, client_sockets in self.channels.items():
                for (client_id, socket) in client_sockets:
                    if invite_client_id == client_id:
                        option = Container(option_id="SERVER_INVITE_OPTION",
                                           option_data = Container(channel_id=channel_id, client_id=invite_client_ids))
                        pdu = Container(id=self.id, option=[option])
                        socket.write(InstantSoupData.peer_pdu.build(pdu))
                        socket.waitForBytesWritten()
        log.debug('PDU: SERVER_INVITE_OPTION - id: %i - SENT' % self.pdu_number)

    def send_regular_pdu(self):

        # simply send all data
        self.send_server_option()

        # sent the option with every fourth pdu (see rfc)
        if self.pdu_number % 4 == 0:
            self.send_server_channel_option()

    def send_server_option(self):

        # define the data to send & send
        option_data = Container(port=self.port)

        option = Container(option_id="SERVER_OPTION",
                   option_data=option_data)

        pdu = Container(id=self.id,
                option=[option])

        data = InstantSoupData.peer_pdu.build(pdu)
        self.send_datagram(data)

        log.debug('PDU: SERVER_OPTION - id: %i - SENT' % self.pdu_number)

        # increment the number of sent packets
        self.pdu_number += 1

    def send_server_channel_option(self):
        if self.channels:

            # define the data to send & send
            option_data = Container(channels=self.channels.keys())

            option = Container(option_id="SERVER_CHANNELS_OPTION",
                       option_data=option_data)

            pdu = Container(id=self.id,
                    option=[option])

            data = InstantSoupData.peer_pdu.build(pdu)
            self.send_datagram(data)

            log.debug('PDU: SERVER_CHANNELS_OPTION - id: %i - SENT' %
                      self.pdu_number)

    def send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def _process_pending_datagrams(self):
        maxlen = self.udp_socket.pendingDatagramSize()

        # loop through all datagrams which are not send yet
        while self.udp_socket.hasPendingDatagrams():
            (datagram, address, _) = self.udp_socket.readDatagram(maxlen)
            packet = InstantSoupData.peer_pdu.parse(datagram)
            uid = packet['id']

            if uid != self.id:
                for option in packet["option"]:
                    if option["option_id"] == "CLIENT_NICK_OPTION":

                        # new client found or client nick was changed
                        if address not in self.lobby_users:
                            self.lobby_users[address] = (uid, option["option_data"])
                            self.send_server_option()

                    if option["option_id"] == "CLIENT_MEMBERSHIP_OPTION":
                        pass

    def sreate_udp_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        self.udp_socket.bind(broadcast_port,
            QtNetwork.QUdpSocket.ReuseAddressHint)
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)
