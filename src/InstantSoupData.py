#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import uuid

from construct import Container, Enum, PrefixedArray, Struct, ULInt16, ULInt8, OptionalGreedyRange, CString, Switch
from PyQt4 import QtGui, QtCore, QtNetwork

log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)

class InstantSoupData(object):
        
    ClientMemberShipOption = PrefixedArray(Struct("Server",
                                                  CString("ServerID"),
                                                  PrefixedArray(CString('Channels'),
                                                                ULInt8("NumChannels"))
                                                  ),
                                           ULInt8("NumServers"))

    ServerInviteOption = Struct("ServerInviteOption",
                                CString("ChannelID"),
                                PrefixedArray(CString("ClientID"),
                                              ULInt8("NumClients")))

    Option = Struct("Option",
                    Enum(ULInt8("OptionID"),
                         CLIENT_NICK_OPTION = 0x01,
                         CLIENT_MEMBERSHIP_OPTION = 0x02,
                         SERVER_OPTION = 0x10,
                         SERVER_CHANNELS_OPTION = 0x11,
                         SERVER_INVITE_OPTION = 0x12),
                    Switch("OptionData",
                           lambda ctx: ctx["OptionID"],
                           {
                                "CLIENT_NICK_OPTION"        : CString('Nickname'),
                                "CLIENT_MEMBERSHIP_OPTION"  : ClientMemberShipOption,
                                "SERVER_OPTION"             : Struct("ServerOption", ULInt16("Port")),
                                "SERVER_CHANNELS_OPTION"    : PrefixedArray(CString("Channels"), ULInt8("NumChannels")),
                                "SERVER_INVITE_OPTION"      : ServerInviteOption
                           }))

    peerPDU = Struct("peerPDU",
                     CString('ClientID'),
                     OptionalGreedyRange(Option))

group_address = QtNetwork.QHostAddress("239.255.99.63")
broadcast_port = 55555

class Client(QtCore.QObject):

    def __init__(self, nickname="Telematik"):
        QtCore.QObject.__init__(self)
        self.nickname = nickname
        self.id = str(uuid.uuid1())
        self.setup_socket()
        self.lobby_users = {} # mapping from client.id to nickname

        self.send_client_nick()

    def setup_socket(self):
        self.udp_socket = QtNetwork.QUdpSocket(self)
        #self.udp_socket.setSocketOption(QtNetwork.QAbstractSocket.MulticastLoopbackOption, 1)
        #self.udp_socket.setSocketOption(QtNetwork.QAbstractSocket.MulticastTtlOption, 255)
        self.udp_socket.bind(broadcast_port, QtNetwork.QUdpSocket.ReuseAddressHint) #QtNetwork.QUdpSocket.ShareAddress
        #log.error("Bind was not succesfull. Probably another Process is already bound to this address")
        self.udp_socket.joinMulticastGroup(group_address)
        self.udp_socket.readyRead.connect(self._process_pending_datagrams)

    def send_client_nick(self):
        data = InstantSoupData.peerPDU.build(Container(ClientID=self.id,
                                                       Option=[Container(OptionID = "CLIENT_NICK_OPTION", OptionData=self.nickname)])
                                            )
        self._send_datagram(data)

    def _process_pending_datagrams(self):
        while self.udp_socket.hasPendingDatagrams():
            datagram, host, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            #print self, "received datagram", datagram
            packet = InstantSoupData.peerPDU.parse(datagram)

            for option in packet["Option"]:
                try:
                    if option["OptionID"] == "CLIENT_NICK_OPTION":
                        if packet["ClientID"] != self.id:
                            # new user name found or user name was changed
                            self.lobby_users[packet["ClientID"]] = option["OptionData"]
                except KeyError:
                    pass

            log.debug((self, "lobby_users:" % self.lobby_users))


    def _send_datagram(self, datagram):
        self.udp_socket.writeDatagram(datagram, group_address, broadcast_port)

    def __repr__(self):
        return "Client(%s, %s)" % (self.nickname, self.id)