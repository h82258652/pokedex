"""Extract all the juicy details from a Gen I game.

This was a pain in the ass!  Thank you SO MUCH to:

    pokered
    pokeyellow
    vixie
    http://www.pastraiser.com/cpu/gameboy/gameboy_opcodes.html
"""
# TODO fix that docstring
# TODO note terminology somewhere: id, index, identifier
from collections import OrderedDict
import hashlib
import io
import logging
from pathlib import Path
import re
import sys

from camel import Camel
from classtools import reify
from construct import *

import pokedex.schema as schema

# TODO set this up to colorcode and use {} formatting
log = logging.getLogger(__name__)

# Known official games, the languages they were released in, and hashes of
# their contents
GAME_RELEASE_MD5SUMS = {
    # Set 0: Original Red/Green, only released in Japan
    'jp-red': {
        'ja': [
            '912d4f77d118390a2e2c42b2016a19d4',  # original
            '4c44844f8d5aa3305a0cf2c95cf96333',  # revision A
        ],
    },
    'jp-green': {
        'ja': [
            'e30ffbab1f239f09b226477d84db1368',  # original
            '16ddd8897092936fbc0e286c6a6b23a2',  # revision A
        ],
    },

    # Set 1: Blue in Japan, split into Red and Blue worldwide
    'jp-blue': {
        'ja': ['c1adf0a77809ac91d905a4828888a2f0'],
    },
    'ww-red': {
        'de': ['8ed0e8d45a81ca34de625d930148a512'],
        'en': ['3d45c1ee9abd5738df46d2bdda8b57dc'],
        'es': ['463c241c8721ab1d1da17c91de9f8a32'],
        'fr': ['669700657cb06ed09371cdbdef69e8a3'],
        'it': ['6468fb0652dde30eb968a44f17c686f1'],
    },
    'ww-blue': {
        'de': ['a1ec7f07c7b4251d5fafc50622d546f8'],
        'en': ['50927e843568814f7ed45ec4f944bd8b'],
        'es': ['6e7663f908334724548a66fc9c386002'],
        'fr': ['35c8154c81abb2ab850689fd28a03515'],
        'it': ['ebe0742b472b3e80a9c6749f06181073'],
    },

    # Set 2: Yellow, pretty much the same everywhere
    # TODO is that true?
    # TODO missing other languages
    'yellow': {
        'en': ['d9290db87b1f0a23b89f99ee4469e34b'],
        'ja': [
            'aa13e886a47fd473da63b7d5ddf2828d',  # original
            '96c1f411671b6e1761cf31884dde0dbb',  # revision A
            '5d9c071cf6eb5f3a697bbcd9311b4d04',  # revision B
        ],
    }
}
# Same, but rearranged to md5 => (game, language)
GAME_RELEASE_MD5SUM_INDEX = {
    md5sum: (game, language)
    for (game, language_sums) in GAME_RELEASE_MD5SUMS.items()
    for (language, md5sums) in language_sums.items()
    for md5sum in md5sums
}


# ------------------------------------------------------------------------------
# Game structure stuff
#
# A lot of this was made much, much easier by the work done on pokered:
# https://github.com/pret/pokered
# Thank y'all so much!
# TODO possibly some of this should be in a shared place, not this file


GROWTH_RATES = {
    0: 'growth-rate.medium',
    3: 'growth-rate.medium-slow',
    4: 'growth-rate.fast',
    5: 'growth-rate.slow',
}

EVOLUTION_TRIGGERS = {
    1: 'evolution-trigger.level-up',
    2: 'evolution-trigger.use-item',
    3: 'evolution-trigger.trade',
}

# TODO these are loci, not enums, so hardcoding all their identifiers here
# makes me nonspecifically uncomfortable
POKEMON_IDENTIFIERS = {
    1: 'pokemon.bulbasaur',
    2: 'pokemon.ivysaur',
    3: 'pokemon.venusaur',
    4: 'pokemon.charmander',
    5: 'pokemon.charmeleon',
    6: 'pokemon.charizard',
    7: 'pokemon.squirtle',
    8: 'pokemon.wartortle',
    9: 'pokemon.blastoise',
    10: 'pokemon.caterpie',
    11: 'pokemon.metapod',
    12: 'pokemon.butterfree',
    13: 'pokemon.weedle',
    14: 'pokemon.kakuna',
    15: 'pokemon.beedrill',
    16: 'pokemon.pidgey',
    17: 'pokemon.pidgeotto',
    18: 'pokemon.pidgeot',
    19: 'pokemon.rattata',
    20: 'pokemon.raticate',
    21: 'pokemon.spearow',
    22: 'pokemon.fearow',
    23: 'pokemon.ekans',
    24: 'pokemon.arbok',
    25: 'pokemon.pikachu',
    26: 'pokemon.raichu',
    27: 'pokemon.sandshrew',
    28: 'pokemon.sandslash',
    29: 'pokemon.nidoran-f',
    30: 'pokemon.nidorina',
    31: 'pokemon.nidoqueen',
    32: 'pokemon.nidoran-m',
    33: 'pokemon.nidorino',
    34: 'pokemon.nidoking',
    35: 'pokemon.clefairy',
    36: 'pokemon.clefable',
    37: 'pokemon.vulpix',
    38: 'pokemon.ninetales',
    39: 'pokemon.jigglypuff',
    40: 'pokemon.wigglytuff',
    41: 'pokemon.zubat',
    42: 'pokemon.golbat',
    43: 'pokemon.oddish',
    44: 'pokemon.gloom',
    45: 'pokemon.vileplume',
    46: 'pokemon.paras',
    47: 'pokemon.parasect',
    48: 'pokemon.venonat',
    49: 'pokemon.venomoth',
    50: 'pokemon.diglett',
    51: 'pokemon.dugtrio',
    52: 'pokemon.meowth',
    53: 'pokemon.persian',
    54: 'pokemon.psyduck',
    55: 'pokemon.golduck',
    56: 'pokemon.mankey',
    57: 'pokemon.primeape',
    58: 'pokemon.growlithe',
    59: 'pokemon.arcanine',
    60: 'pokemon.poliwag',
    61: 'pokemon.poliwhirl',
    62: 'pokemon.poliwrath',
    63: 'pokemon.abra',
    64: 'pokemon.kadabra',
    65: 'pokemon.alakazam',
    66: 'pokemon.machop',
    67: 'pokemon.machoke',
    68: 'pokemon.machamp',
    69: 'pokemon.bellsprout',
    70: 'pokemon.weepinbell',
    71: 'pokemon.victreebel',
    72: 'pokemon.tentacool',
    73: 'pokemon.tentacruel',
    74: 'pokemon.geodude',
    75: 'pokemon.graveler',
    76: 'pokemon.golem',
    77: 'pokemon.ponyta',
    78: 'pokemon.rapidash',
    79: 'pokemon.slowpoke',
    80: 'pokemon.slowbro',
    81: 'pokemon.magnemite',
    82: 'pokemon.magneton',
    83: 'pokemon.farfetchd',
    84: 'pokemon.doduo',
    85: 'pokemon.dodrio',
    86: 'pokemon.seel',
    87: 'pokemon.dewgong',
    88: 'pokemon.grimer',
    89: 'pokemon.muk',
    90: 'pokemon.shellder',
    91: 'pokemon.cloyster',
    92: 'pokemon.gastly',
    93: 'pokemon.haunter',
    94: 'pokemon.gengar',
    95: 'pokemon.onix',
    96: 'pokemon.drowzee',
    97: 'pokemon.hypno',
    98: 'pokemon.krabby',
    99: 'pokemon.kingler',
    100: 'pokemon.voltorb',
    101: 'pokemon.electrode',
    102: 'pokemon.exeggcute',
    103: 'pokemon.exeggutor',
    104: 'pokemon.cubone',
    105: 'pokemon.marowak',
    106: 'pokemon.hitmonlee',
    107: 'pokemon.hitmonchan',
    108: 'pokemon.lickitung',
    109: 'pokemon.koffing',
    110: 'pokemon.weezing',
    111: 'pokemon.rhyhorn',
    112: 'pokemon.rhydon',
    113: 'pokemon.chansey',
    114: 'pokemon.tangela',
    115: 'pokemon.kangaskhan',
    116: 'pokemon.horsea',
    117: 'pokemon.seadra',
    118: 'pokemon.goldeen',
    119: 'pokemon.seaking',
    120: 'pokemon.staryu',
    121: 'pokemon.starmie',
    122: 'pokemon.mr-mime',
    123: 'pokemon.scyther',
    124: 'pokemon.jynx',
    125: 'pokemon.electabuzz',
    126: 'pokemon.magmar',
    127: 'pokemon.pinsir',
    128: 'pokemon.tauros',
    129: 'pokemon.magikarp',
    130: 'pokemon.gyarados',
    131: 'pokemon.lapras',
    132: 'pokemon.ditto',
    133: 'pokemon.eevee',
    134: 'pokemon.vaporeon',
    135: 'pokemon.jolteon',
    136: 'pokemon.flareon',
    137: 'pokemon.porygon',
    138: 'pokemon.omanyte',
    139: 'pokemon.omastar',
    140: 'pokemon.kabuto',
    141: 'pokemon.kabutops',
    142: 'pokemon.aerodactyl',
    143: 'pokemon.snorlax',
    144: 'pokemon.articuno',
    145: 'pokemon.zapdos',
    146: 'pokemon.moltres',
    147: 'pokemon.dratini',
    148: 'pokemon.dragonair',
    149: 'pokemon.dragonite',
    150: 'pokemon.mewtwo',
    151: 'pokemon.mew',
}

TYPE_IDENTIFIERS = {
    0: 'type.normal',
    1: 'type.fighting',
    2: 'type.flying',
    3: 'type.poison',
    4: 'type.ground',
    5: 'type.rock',
    #6: 'type.bird',
    7: 'type.bug',
    8: 'type.ghost',
    9: 'type.steel',
    20: 'type.fire',
    21: 'type.water',
    22: 'type.grass',
    23: 'type.electric',
    24: 'type.psychic',
    25: 'type.ice',
    26: 'type.dragon',
    27: 'type.dark',
}

MOVE_IDENTIFIERS = {
    # TODO stupid hack for initial moveset
    0: '--',

    1: 'move.pound',
    2: 'move.karate-chop',
    3: 'move.double-slap',
    4: 'move.comet-punch',
    5: 'move.mega-punch',
    6: 'move.pay-day',
    7: 'move.fire-punch',
    8: 'move.ice-punch',
    9: 'move.thunder-punch',
    10: 'move.scratch',
    11: 'move.vice-grip',
    12: 'move.guillotine',
    13: 'move.razor-wind',
    14: 'move.swords-dance',
    15: 'move.cut',
    16: 'move.gust',
    17: 'move.wing-attack',
    18: 'move.whirlwind',
    19: 'move.fly',
    20: 'move.bind',
    21: 'move.slam',
    22: 'move.vine-whip',
    23: 'move.stomp',
    24: 'move.double-kick',
    25: 'move.mega-kick',
    26: 'move.jump-kick',
    27: 'move.rolling-kick',
    28: 'move.sand-attack',
    29: 'move.headbutt',
    30: 'move.horn-attack',
    31: 'move.fury-attack',
    32: 'move.horn-drill',
    33: 'move.tackle',
    34: 'move.body-slam',
    35: 'move.wrap',
    36: 'move.take-down',
    37: 'move.thrash',
    38: 'move.double-edge',
    39: 'move.tail-whip',
    40: 'move.poison-sting',
    41: 'move.twineedle',
    42: 'move.pin-missile',
    43: 'move.leer',
    44: 'move.bite',
    45: 'move.growl',
    46: 'move.roar',
    47: 'move.sing',
    48: 'move.supersonic',
    49: 'move.sonic-boom',
    50: 'move.disable',
    51: 'move.acid',
    52: 'move.ember',
    53: 'move.flamethrower',
    54: 'move.mist',
    55: 'move.water-gun',
    56: 'move.hydro-pump',
    57: 'move.surf',
    58: 'move.ice-beam',
    59: 'move.blizzard',
    60: 'move.psybeam',
    61: 'move.bubble-beam',
    62: 'move.aurora-beam',
    63: 'move.hyper-beam',
    64: 'move.peck',
    65: 'move.drill-peck',
    66: 'move.submission',
    67: 'move.low-kick',
    68: 'move.counter',
    69: 'move.seismic-toss',
    70: 'move.strength',
    71: 'move.absorb',
    72: 'move.mega-drain',
    73: 'move.leech-seed',
    74: 'move.growth',
    75: 'move.razor-leaf',
    76: 'move.solar-beam',
    77: 'move.poison-powder',
    78: 'move.stun-spore',
    79: 'move.sleep-powder',
    80: 'move.petal-dance',
    81: 'move.string-shot',
    82: 'move.dragon-rage',
    83: 'move.fire-spin',
    84: 'move.thunder-shock',
    85: 'move.thunderbolt',
    86: 'move.thunder-wave',
    87: 'move.thunder',
    88: 'move.rock-throw',
    89: 'move.earthquake',
    90: 'move.fissure',
    91: 'move.dig',
    92: 'move.toxic',
    93: 'move.confusion',
    94: 'move.psychic',
    95: 'move.hypnosis',
    96: 'move.meditate',
    97: 'move.agility',
    98: 'move.quick-attack',
    99: 'move.rage',
    100: 'move.teleport',
    101: 'move.night-shade',
    102: 'move.mimic',
    103: 'move.screech',
    104: 'move.double-team',
    105: 'move.recover',
    106: 'move.harden',
    107: 'move.minimize',
    108: 'move.smokescreen',
    109: 'move.confuse-ray',
    110: 'move.withdraw',
    111: 'move.defense-curl',
    112: 'move.barrier',
    113: 'move.light-screen',
    114: 'move.haze',
    115: 'move.reflect',
    116: 'move.focus-energy',
    117: 'move.bide',
    118: 'move.metronome',
    119: 'move.mirror-move',
    120: 'move.self-destruct',
    121: 'move.egg-bomb',
    122: 'move.lick',
    123: 'move.smog',
    124: 'move.sludge',
    125: 'move.bone-club',
    126: 'move.fire-blast',
    127: 'move.waterfall',
    128: 'move.clamp',
    129: 'move.swift',
    130: 'move.skull-bash',
    131: 'move.spike-cannon',
    132: 'move.constrict',
    133: 'move.amnesia',
    134: 'move.kinesis',
    135: 'move.soft-boiled',
    136: 'move.high-jump-kick',
    137: 'move.glare',
    138: 'move.dream-eater',
    139: 'move.poison-gas',
    140: 'move.barrage',
    141: 'move.leech-life',
    142: 'move.lovely-kiss',
    143: 'move.sky-attack',
    144: 'move.transform',
    145: 'move.bubble',
    146: 'move.dizzy-punch',
    147: 'move.spore',
    148: 'move.flash',
    149: 'move.psywave',
    150: 'move.splash',
    151: 'move.acid-armor',
    152: 'move.crabhammer',
    153: 'move.explosion',
    154: 'move.fury-swipes',
    155: 'move.bonemerang',
    156: 'move.rest',
    157: 'move.rock-slide',
    158: 'move.hyper-fang',
    159: 'move.sharpen',
    160: 'move.conversion',
    161: 'move.tri-attack',
    162: 'move.super-fang',
    163: 'move.slash',
    164: 'move.substitute',
    165: 'move.struggle',
}


def unbank(*args):
    """Convert a "bank" identifier, XX:YYYY, to a real address.  The Game Boy
    is all about banks internally, and it's what pokered uses, so I've kept
    them intact in this file.

    The scheme is fairly simple:
    - XX is the bank; YYYY is an address.  Banks are 0x4000 bytes.
    - For bank 00, YYYY is already a real address, and should be between 0x0000
      and 0x4000.
    - For any other bank, YYYY is between 0x4000 and 0x8000, and they're just
      arranged in order.  So for bank 01, YYYY is already a real address; for
      bank 02, you add 0x4000; and so on.

    Accepts either two ints (XX and YYYY) or a string in the form 'XX:YYYY'.
    """
    if len(args) == 1:
        banked_address, = args
        banks, addrs = banked_address.split(':')
        bank = int(banks, 16)
        addr = int(addrs, 16)
    else:
        bank, addr = args

    if bank:
        assert 0x4000 <= addr < 0x8000
        return addr + (bank - 1) * 0x4000
    else:
        assert 0 <= addr < 0x4000
        return addr


def bank(addr):
    """Inverse of the above transformation."""
    if addr < 0x4000:
        return 0, addr
    bank, addr = divmod(addr, 0x4000)
    addr += 0x4000
    return bank, addr


EN_TEXT_MAP = {
    # Sort of faux movement macros
    0x00: "",   # "Start text"?
    0x4E: "\n", # Move to next line
    0x49: "\f", # Start a new Pokédex page
    0x5F: ".",   # End of Pokédex entry, adds a period

    0x05: "ガ",
    0x06: "ギ",
    0x07: "グ",
    0x08: "ゲ",
    0x09: "ゴ",
    0x0A: "ザ",
    0x0B: "ジ",
    0x0C: "ズ",
    0x0D: "ゼ",
    0x0E: "ゾ",
    0x0F: "ダ",
    0x10: "ヂ",
    0x11: "ヅ",
    0x12: "デ",
    0x13: "ド",
    0x19: "バ",
    0x1A: "ビ",
    0x1B: "ブ",
    0x1C: "ボ",
    0x26: "が",
    0x27: "ぎ",
    0x28: "ぐ",
    0x29: "げ",
    0x2A: "ご",
    0x2B: "ざ",
    0x2C: "じ",
    0x2D: "ず",
    0x2E: "ぜ",
    0x2F: "ぞ",
    0x30: "だ",
    0x31: "ぢ",
    0x32: "づ",
    0x33: "で",
    0x34: "ど",
    0x3A: "ば",
    0x3B: "び",
    0x3C: "ぶ",
    0x3D: "べ",
    0x3E: "ぼ",
    0x40: "パ",
    0x41: "ピ",
    0x42: "プ",
    0x43: "ポ",
    0x44: "ぱ",
    0x45: "ぴ",
    0x46: "ぷ",
    0x47: "ぺ",
    0x48: "ぽ",
    0x80: "ア",
    0x81: "イ",
    0x82: "ウ",
    0x83: "エ",
    0x84: "ォ",
    0x85: "カ",
    0x86: "キ",
    0x87: "ク",
    0x88: "ケ",
    0x89: "コ",
    0x8A: "サ",
    0x8B: "シ",
    0x8C: "ス",
    0x8D: "セ",
    0x8E: "ソ",
    0x8F: "タ",
    0x90: "チ",
    0x91: "ツ",
    0x92: "テ",
    0x93: "ト",
    0x94: "ナ",
    0x95: "ニ",
    0x96: "ヌ",
    0x97: "ネ",
    0x98: "ノ",
    0x99: "ハ",
    0x9A: "ヒ",
    0x9B: "フ",
    0x9C: "ホ",
    0x9D: "マ",
    0x9E: "ミ",
    0x9F: "ム",
    0xA0: "メ",
    0xA1: "モ",
    0xA2: "ヤ",
    0xA3: "ユ",
    0xA4: "ヨ",
    0xA5: "ラ",
    0xA6: "ル",
    0xA7: "レ",
    0xA8: "ロ",
    0xA9: "ワ",
    0xAA: "ヲ",
    0xAB: "ン",
    0xAC: "ッ",
    0xAD: "ャ",
    0xAE: "ュ",
    0xAF: "ョ",
    0xB0: "ィ",
    0xB1: "あ",
    0xB2: "い",
    0xB3: "う",
    0xB4: "え",
    0xB5: "お",
    0xB6: "か",
    0xB7: "き",
    0xB8: "く",
    0xB9: "け",
    0xBA: "こ",
    0xBB: "さ",
    0xBC: "し",
    0xBD: "す",
    0xBE: "せ",
    0xBF: "そ",
    0xC0: "た",
    0xC1: "ち",
    0xC2: "つ",
    0xC3: "て",
    0xC4: "と",
    0xC5: "な",
    0xC6: "に",
    0xC7: "ぬ",
    0xC8: "ね",
    0xC9: "の",
    0xCA: "は",
    0xCB: "ひ",
    0xCC: "ふ",
    0xCD: "へ",
    0xCE: "ほ",
    0xCF: "ま",
    0xD0: "み",
    0xD1: "む",
    0xD2: "め",
    0xD3: "も",
    0xD4: "や",
    0xD5: "ゆ",
    0xD6: "よ",
    0xD7: "ら",
    0xD8: "り",
    0xD9: "る",
    0xDA: "れ",
    0xDB: "ろ",
    0xDC: "わ",
    0xDD: "を",
    0xDE: "ん",
    0xDF: "っ",
    0xE0: "ゃ",
    0xE1: "ゅ",
    0xE2: "ょ",
    0xE3: "ー",

    0x50: "@",
    0x54: "#",
    0x54: "POKé",
    0x75: "…",

    0x79: "┌",
    0x7A: "─",
    0x7B: "┐",
    0x7C: "│",
    0x7D: "└",
    0x7E: "┘",

    0x74: "№",

    0x7F: " ",
    0x80: "A",
    0x81: "B",
    0x82: "C",
    0x83: "D",
    0x84: "E",
    0x85: "F",
    0x86: "G",
    0x87: "H",
    0x88: "I",
    0x89: "J",
    0x8A: "K",
    0x8B: "L",
    0x8C: "M",
    0x8D: "N",
    0x8E: "O",
    0x8F: "P",
    0x90: "Q",
    0x91: "R",
    0x92: "S",
    0x93: "T",
    0x94: "U",
    0x95: "V",
    0x96: "W",
    0x97: "X",
    0x98: "Y",
    0x99: "Z",
    0x9A: "(",
    0x9B: ")",
    0x9C: ":",
    0x9D: ";",
    0x9E: "[",
    0x9F: "]",
    0xA0: "a",
    0xA1: "b",
    0xA2: "c",
    0xA3: "d",
    0xA4: "e",
    0xA5: "f",
    0xA6: "g",
    0xA7: "h",
    0xA8: "i",
    0xA9: "j",
    0xAA: "k",
    0xAB: "l",
    0xAC: "m",
    0xAD: "n",
    0xAE: "o",
    0xAF: "p",
    0xB0: "q",
    0xB1: "r",
    0xB2: "s",
    0xB3: "t",
    0xB4: "u",
    0xB5: "v",
    0xB6: "w",
    0xB7: "x",
    0xB8: "y",
    0xB9: "z",
    0xBA: "é",
    0xBB: "'d",
    0xBC: "'l",
    0xBD: "'s",
    0xBE: "'t",
    0xBF: "'v",
    0xE0: "'",
    0xE3: "-",
    0xE4: "'r",
    0xE5: "'m",
    0xE6: "?",
    0xE7: "!",
    0xE8: ".",
    0xED: "▶",
    0xEF: "♂",
    0xF0: "¥",
    0xF1: "×",
    0xF3: "/",
    0xF4: ",",
    0xF5: "♀",
    0xF6: "0",
    0xF7: "1",
    0xF8: "2",
    0xF9: "3",
    0xFA: "4",
    0xFB: "5",
    0xFC: "6",
    0xFD: "7",
    0xFE: "8",
    0xFF: "9",
}

JA_CHARMAP = {
    **EN_TEXT_MAP,
    0x05: "ガ",
    0x06: "ギ",
    0x07: "グ",
    0x08: "ゲ",
    0x09: "ゴ",
    0x0A: "ザ",
    0x0B: "ジ",
    0x0C: "ズ",
    0x0D: "ゼ",
    0x0E: "ゾ",
    0x0F: "ダ",
    0x10: "ヂ",
    0x11: "ヅ",
    0x12: "デ",
    0x13: "ド",
    0x19: "バ",
    0x1A: "ビ",
    0x1B: "ブ",
    0x1C: "ボ",
    0x26: "が",
    0x27: "ぎ",
    0x28: "ぐ",
    0x29: "げ",
    0x2A: "ご",
    0x2B: "ざ",
    0x2C: "じ",
    0x2D: "ず",
    0x2E: "ぜ",
    0x2F: "ぞ",
    0x30: "だ",
    0x31: "ぢ",
    0x32: "づ",
    0x33: "で",
    0x34: "ど",
    0x3A: "ば",
    0x3B: "び",
    0x3C: "ぶ",
    0x3D: "べ",
    0x3E: "ぼ",
    0x40: "パ",
    0x41: "ピ",
    0x42: "プ",
    0x43: "ポ",
    0x44: "ぱ",
    0x45: "ぴ",
    0x46: "ぷ",
    0x47: "ぺ",
    0x48: "ぽ",
    0x80: "ア",
    0x81: "イ",
    0x82: "ウ",
    0x83: "エ",
    0x84: "ォ",
    0x85: "カ",
    0x86: "キ",
    0x87: "ク",
    0x88: "ケ",
    0x89: "コ",
    0x8A: "サ",
    0x8B: "シ",
    0x8C: "ス",
    0x8D: "セ",
    0x8E: "ソ",
    0x8F: "タ",
    0x90: "チ",
    0x91: "ツ",
    0x92: "テ",
    0x93: "ト",
    0x94: "ナ",
    0x95: "ニ",
    0x96: "ヌ",
    0x97: "ネ",
    0x98: "ノ",
    0x99: "ハ",
    0x9A: "ヒ",
    0x9B: "フ",
    0x9C: "ホ",
    0x9D: "マ",
    0x9E: "ミ",
    0x9F: "ム",
    0xA0: "メ",
    0xA1: "モ",
    0xA2: "ヤ",
    0xA3: "ユ",
    0xA4: "ヨ",
    0xA5: "ラ",
    0xA6: "ル",
    0xA7: "レ",
    0xA8: "ロ",
    0xA9: "ワ",
    0xAA: "ヲ",
    0xAB: "ン",
    0xAC: "ッ",
    0xAD: "ャ",
    0xAE: "ュ",
    0xAF: "ョ",
    0xB0: "ィ",
    0xB1: "あ",
    0xB2: "い",
    0xB3: "う",
    0xB4: "え",
    0xB5: "お",
    0xB6: "か",
    0xB7: "き",
    0xB8: "く",
    0xB9: "け",
    0xBA: "こ",
    0xBB: "さ",
    0xBC: "し",
    0xBD: "す",
    0xBE: "せ",
    0xBF: "そ",
    0xC0: "た",
    0xC1: "ち",
    0xC2: "つ",
    0xC3: "て",
    0xC4: "と",
    0xC5: "な",
    0xC6: "に",
    0xC7: "ぬ",
    0xC8: "ね",
    0xC9: "の",
    0xCA: "は",
    0xCB: "ひ",
    0xCC: "ふ",
    0xCD: "へ",
    0xCE: "ほ",
    0xCF: "ま",
    0xD0: "み",
    0xD1: "む",
    0xD2: "め",
    0xD3: "も",
    0xD4: "や",
    0xD5: "ゆ",
    0xD6: "よ",
    0xD7: "ら",
    0xD8: "り",
    0xD9: "る",
    0xDA: "れ",
    0xDB: "ろ",
    0xDC: "わ",
    0xDD: "を",
    0xDE: "ん",
    0xDF: "っ",
    0xE0: "ゃ",
    0xE1: "ゅ",
    0xE2: "ょ",
    0xE3: "ー",
    0xE9: "ァ",
}
for n in range(0x100):
    if not n in JA_CHARMAP:
        JA_CHARMAP[n] = '�'

# ty, tachyon
DE_FR_TEXT_MAP = dict(enumerate([
    # 0x0X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x1X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x2X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x3X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x4X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x5X
    "", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x6X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x7X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", " ",
    # 0x8X
    "A", "B", "C", "D", "E", "F", "G", "H",
    "I", "J", "K", "L", "M", "N", "O", "P",
    # 0x9X
    "Q", "R", "S", "T", "U", "V", "W", "X",
    "Y", "Z", "(", ")", ":", ";", "[", "]",
    # 0xAX
    "a", "b", "c", "d", "e", "f", "g", "h",
    "i", "j", "k", "l", "m", "n", "o", "p",
    # 0xBX
    "q", "r", "s", "t", "u", "v", "w", "x",
    "y", "z", "à", "è", "é", "ù", "ß", "ç",
    # 0xCX
    "Ä", "Ö", "Ü", "ä", "ö", "ü", "ë", "ï",
    "â", "ô", "û", "ê", "î", "�", "�", "�",
    # 0xDX
    "�", "�", "�", "�", "cʼ", "dʼ", "jʼ", "lʼ",
    "mʼ", "nʼ", "pʼ", "sʼ", "ʼs", "tʼ", "uʼ", "yʼ",
    # 0xEX
    "'", "P\u200dk", "M\u200dn", "-", "¿", "¡", "?", "!",
    ".", "ァ", "ゥ", "ェ", "▹", "▸", "▾", "♂",
    # 0xFX
    "$", "×", ".", "/", ",", "♀", "0", "1",
    "2", "3", "4", "5", "6", "7", "8", "9",
]))
DE_FR_TEXT_MAP.update({
    0x00: "",   # "Start text"?
    0x4E: "\n", # Move to next line
    0x49: "\f", # Start a new Pokédex page
    0x5F: ".",   # End of Pokédex entry, adds a period
    0x54: "POKé",
})

ES_IT_CHARMAP = dict(enumerate([
    # 0x0X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x1X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x2X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x3X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x4X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x5X
    "@", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x6X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", "�",
    # 0x7X
    "�", "�", "�", "�", "�", "�", "�", "�",
    "�", "�", "�", "�", "�", "�", "�", " ",
    # 0x8X
    "A", "B", "C", "D", "E", "F", "G", "H",
    "I", "J", "K", "L", "M", "N", "O", "P",
    # 0x9X
    "Q", "R", "S", "T", "U", "V", "W", "X",
    "Y", "Z", "(", ")", ":", ";", "[", "]",
    # 0xAX
    "a", "b", "c", "d", "e", "f", "g", "h",
    "i", "j", "k", "l", "m", "n", "o", "p",
    # 0xBX
    "q", "r", "s", "t", "u", "v", "w", "x",
    "y", "z", "à", "è", "é", "ù", "À", "Á",
    # 0xCX
    "Ä", "Ö", "Ü", "ä", "ö", "ü", "È", "É",
    "Ì", "Í", "Ñ", "Ò", "Ó", "Ù", "Ú", "á",
    # 0xDX
    "ì", "í", "ñ", "ò", "ó", "ú", "º", "&",
    "ʼd", "ʼl", "ʼm", "ʼr", "ʼs", "ʼt", "ʼv", " ",
    # 0xEX
    "'", "P\u200dk", "M\u200dn", "-", "¿", "¡", "?", "!",
    ".", "ァ", "ゥ", "ェ", "▹", "▸", "▾", "♂",
    # 0xFX
    "$", "×", ".", "/", ",", "♀", "0", "1",
    "2", "3", "4", "5", "6", "7", "8", "9"
]))
ES_IT_CHARMAP.update({
    0x00: "",   # "Start text"?
    0x4E: "\n", # Move to next line
    0x49: "\f", # Start a new Pokédex page
    0x5F: ".",   # End of Pokédex entry, adds a period
    0x54: "POKé",
})


class PokemonString:
    """A string encoded using the goofy Gen I scheme."""
    def __init__(self, raw):
        self.raw = raw

    def decrypt(self, language):
        if language == 'ja':
            charmap = JA_CHARMAP
        elif language == 'en':
            charmap = EN_TEXT_MAP
        elif language in ('es', 'it'):
            charmap = ES_IT_CHARMAP
        elif language in ('de', 'fr'):
            charmap = DE_FR_TEXT_MAP
        else:
            raise ValueError("Not a known language: {!r}".format(language))

        return ''.join(
            charmap.get(ch, '�') for ch in self.raw)


class PokemonCString(Adapter):
    """Construct thing for `PokemonString`."""
    def __init__(self, name, length=None):
        # No matter which charmap, the "end of string" character is always
        # encoded as P
        if length is None:
            subcon = CString(name, terminators=b'P')
        else:
            subcon = String(name, length, padchar=b'P')
        super().__init__(subcon)

    def _encode(self, obj, context):
        raise NotImplementedError

    def _decode(self, obj, context):
        return PokemonString(obj)


class NullTerminatedArray(Subconstruct):
    _peeker = Peek(ULInt8('___'))
    __slots__ = ()

    def __init__(self, subcon):
        super().__init__(subcon)
        self._clear_flag(self.FLAG_COPY_CONTEXT)
        self._set_flag(self.FLAG_DYNAMIC)

    def _parse(self, stream, context):
        from construct.lib import ListContainer
        obj = ListContainer()
        orig_context = context
        while True:
            nextbyte = self._peeker.parse_stream(stream)
            if nextbyte == 0:
                break

            if self.subcon.conflags & self.FLAG_COPY_CONTEXT:
                context = orig_context.__copy__()

            # TODO what if we hit the end of the stream
            obj.append(self.subcon._parse(stream, context))

        # Consume the trailing zero
        stream.read(1)

        return obj

    def _build(self, obj, stream, context):
        raise NotImplementedError

    # TODO ???
    #def _sizeof(self, context):

def IdentEnum(subcon, mapping):
    return Enum(subcon, **{v: k for (k, v) in mapping.items()})



# Game Boy header, at 0x0100
# http://gbdev.gg8.se/wiki/articles/The_Cartridge_Header
# TODO hey!  i wish i had a little cli entry point that would spit this out for a game.  and do other stuff like scan for likely pokemon text or graphics.  that would be really cool in fact.  maybe put this in a gb module and make that exist sometime.
game_boy_header_struct = Struct(
    'game_boy_header',
    # Entry point for the game; generally contains a jump to 0x0150
    String('entry_point', 4),
    # Nintendo logo; must be exactly this or booting will not continue
    Const(
        String('nintendo_logo', 48),
        bytes.fromhex("""
            CE ED 66 66 CC 0D 00 0B 03 73 00 83 00 0C 00 0D
            00 08 11 1F 88 89 00 0E DC CC 6E E6 DD DD D9 99
            BB BB 67 63 6E 0E EC CC DD DC 99 9F BB B9 33 3E
        """.replace('\n', '')),
    ),
    String('title', 11, padchar=b'\x00'),
    String('manufacturer_code', 4),
    ULInt8('cgb_flag'),
    String('new_licensee_code', 2),
    ULInt8('sgb_flag'),  # 3 for super game boy support
    ULInt8('cartridge_type'),
    ULInt8('rom_size'),
    ULInt8('ram_size'),
    ULInt8('region_code'),  # 0 for japan, 1 for not japan
    ULInt8('old_licensee_code'),  # 0x33 means to use licensee_code
    ULInt8('game_version'),
    ULInt8('header_checksum'),
    UBInt16('cart_checksum'),
)


# The mother lode — Pokémon base stats
pokemon_struct = Struct(
    'pokemon',
    ULInt8('pokedex_number'),
    ULInt8('base_hp'),
    ULInt8('base_attack'),
    ULInt8('base_defense'),
    ULInt8('base_speed'),
    ULInt8('base_special'),
    IdentEnum(ULInt8('type1'), TYPE_IDENTIFIERS),
    IdentEnum(ULInt8('type2'), TYPE_IDENTIFIERS),
    ULInt8('catch_rate'),
    ULInt8('base_experience'),
    # TODO ????  "sprite dimensions"
    ULInt8('_sprite_dimensions'),
    ULInt16('front_sprite_pointer'),
    ULInt16('back_sprite_pointer'),
    # TODO somehow rig this to discard trailing zeroes; there's a paddedstring that does it
    Array(4, IdentEnum(ULInt8('initial_moveset'), MOVE_IDENTIFIERS)),
    IdentEnum(ULInt8('growth_rate'), GROWTH_RATES),
    # TODO argh, this is a single huge integer; i want an array, but then i lose the byteswapping!
    Bitwise(
        BitField('machines', 7 * 8, swapped=True),
    ),
    Padding(1),
)

pokemon_name_struct = PokemonCString('pokemon_name', 10)


evos_moves_struct = Struct(
    'evos_moves',
    NullTerminatedArray(
        Struct(
            'evolutions',
            IdentEnum(ULInt8('evo_trigger'), EVOLUTION_TRIGGERS),
            Embedded(Switch(
                'evo_arguments',
                lambda ctx: ctx.evo_trigger, {
                    'evolution-trigger.level-up': Struct(
                        '---',
                        ULInt8('evo_level'),
                    ),
                    'evolution-trigger.use-item': Struct(
                        '---',
                        # TODO item enum too wow!
                        ULInt8('evo_item'),
                        # TODO ??? always seems to be 1
                        ULInt8('evo_level'),
                    ),
                    # TODO ??? always seems to be 1 here too
                    'evolution-trigger.trade': Struct(
                        '---',
                        ULInt8('evo_level'),
                    ),
                },
            )),
            # TODO alas, the species here is a number, because it's an internal
            # id and we switch those back using data from the game...
            ULInt8('evo_species'),
        ),
    ),
    NullTerminatedArray(
        Struct(
            'level_up_moves',
            ULInt8('level'),
            IdentEnum(ULInt8('move'), MOVE_IDENTIFIERS),
            Peek(ULInt8('_end')),
        ),
    ),
)
evos_moves_pointer = Struct(
    'xxx',
    ULInt16('offset'),
    # TODO hardcoded as the same bank, ugh
    Pointer(lambda ctx: ctx.offset + (0xE - 1) * 0x4000, evos_moves_struct),
)

pokedex_flavor_struct = Struct(
    'pokedex_flavor',
    PokemonCString('species'),
    # TODO HA HA FUCK ME, SOME GAMES USE METRIC SOME (OK JUST THE US) USE IMPERIAL
    #ULInt8('height_feet'),
    #ULInt8('height_inches'),
    #ULInt16('weight_pounds'),
    ULInt8('height_decimeters'),
    ULInt16('weight_hectograms'),
    # This appears to technically be a string containing a single macro, for
    # "load other string from this address", but it always takes this same form
    # so there's no need to actually evaluate it.
    Const(ULInt8('macro'), 0x17),  # 0x17 is the "far" macro
    ULInt16('address'),
    ULInt8('bank'),
    Const(ULInt8('nul'), 0x50),  # faux nul marking the end of the string
    Pointer(
        lambda ctx: ctx.address + (ctx.bank - 1) * 0x4000,
        PokemonCString('flavor_text'),
    ),
)
# TODO this works very awkwardly as a struct
pokedex_flavor_pointer = Struct(
    'xxx',
    ULInt16('offset'),
    # TODO hardcoded 0x10, same bank
    # TODO this has to be on-demand because missingno's struct is actually bogus!
    OnDemandPointer(lambda ctx: ctx.offset + (0x10 - 1) * 0x4000, pokedex_flavor_struct),
)


class CartDetectionError(Exception):
    pass


class RBYCart:
    NUM_POKEMON = 151
    NUM_MOVES = 165
    NUM_MACHINES = 55

    def __init__(self, path):
        with path.open('rb') as f:
            self.data = f.read()
        self.stream = io.BytesIO(self.data)
        self.path = path

        # Scrape these first; language detection relies on examining text
        self.addrs = self.detect_addresses()

        self.game, self.language = self.detect_game()

        # And snag this before anything else happens; prevents some silly
        # problems where a reified property seeks, then tries to read this, and
        # it ends up seeking again
        self.max_pokemon_index

    def detect_addresses(self):
        """The addresses of some important landmarks can vary between versions
        and languages.  Attempt to detect them automatically.

        Return a dict of raw file offsets.  The keys are the names used in the
        pokered project.
        """
        # The base stats are always in the same place in RBY, and only slightly
        # off in RG.  Not sure why!  But it hopefully means recompilation
        # doesn't affect them.
        addresses = {
            # These ones have, thusfar, defied automatic detection, as they're
            # just part of a big old block of data — so I can't just look for
            # code nearby.
            # TODO these are for rby; fix for rg, and maybe y?
            'BaseStats': unbank('0E:43DE'),
            'MewBaseStats': unbank('01:425B'),
        }

        # For everything else, the general approach is to find some assembly
        # code that appears just before the data of interest.  It's pretty
        # hacky, but since translators (and even modders) would have little
        # reason to rearrange functions or inject new ones in these odd places,
        # it ought to work well enough.  And it's better than ferreting out and
        # hard-coding piles of addresses.
        # The only hard part is that assembly code that contains an address
        # won't work, since that address will also vary per game.
        # Each of the landmarks used here appears in every official cartridge
        # exactly once.

        # This is an entire function used by the Pokédex and which immediately
        # precedes all the flavor text.
        asm_DrawTileLine = bytes.fromhex('c5d5 7019 0d20 fbd1 c1c9')
        try:
            idx = self.data.index(asm_DrawTileLine)
        except ValueError:
            raise CartDetectionError("Can't find flavor text pointers")
        addresses['PokedexEntryPointers'] = idx + len(asm_DrawTileLine)

        # This is a helper function for figuring out moves, followed by another
        # 5-byte function, then the table of evolutions and moves.
        asm_WriteMonMoves_ShiftMoveData = bytes.fromhex('0e03 131a 220d 20fa c9')
        try:
            idx = self.data.index(asm_WriteMonMoves_ShiftMoveData)
        except ValueError:
            raise CartDetectionError("Can't find evolution and moveset table")
        addresses['EvosMovesPointerTable'] = idx + len(asm_WriteMonMoves_ShiftMoveData) + 5

        # Finding TMs is a bit harder.  They come right after a function for
        # looking up a TM number, which is very short and very full of
        # addresses.  So here's a regex.
        # `wd11e` is some address used all over the game for passing arguments
        # around, which unfortunately also differs from language to language.
        # In English it is, unsurprisingly, 0xD11E.
        # `TechnicalMachines` is the address we're looking for, which should
        # immediately follow what this matches.
        asm_TMToMove_rx = re.compile(rb'''
            \xfa (..)   # ld a, [wd11e]
            \x3d        # dec a
            \x21 (..)   # ld hl, TechnicalMachines
            \x06 \x00   # ld b, $0
            \x4f        # ld c, a
            \x09        # add hl, bc
            \x7e        # ld a, [hl]
            \xea \1     # ld [wd11e], a
            \xc9        # ret
        ''', flags=re.DOTALL | re.VERBOSE)
        for match in asm_TMToMove_rx.finditer(self.data):
            matched_addr = ULInt16('...').parse(match.group(2))
            tentative_addr = match.end()
            # Remember, addresses don't include the bank!
            _, banked_addr = bank(tentative_addr)
            if matched_addr == banked_addr:
                asm_wd11e_addr = match.group(1)
                addresses['TechnicalMachines'] = tentative_addr
                break
            # TODO should there really be more than one match?
        else:
            raise CartDetectionError("Can't find technical machines list")

        # Pokédex order is similarly tricky.  Much like the above, this
        # function converts a Pokémon's game index to its national dex number.
        # These are almost immediately after the Pokédex entries themselves,
        # but this actually seems easier than figuring out where a table of
        # pointers ends.
        asm_IndexToPokedex_rx = re.compile(rb'''
            \xc5        # push bc
            \xe5        # push hl
            \xfa (..)   # ld a,[wd11e]
            \x3d        # dec a
            \x21 (..)   # ld hl,PokedexOrder
            \x06 \x00   # ld b,0
            \x4f        # ld c,a
            \x09        # add hl,bc
            \x7e        # ld a,[hl]
            \xea \1     # ld [wd11e],a
            \xe1        # pop hl
            \xc1        # pop bc
            \xc9        # ret
        ''', flags=re.DOTALL | re.VERBOSE)
        for match in asm_IndexToPokedex_rx.finditer(self.data):
            matched_addr = ULInt16('...').parse(match.group(2))
            tentative_addr = match.end()
            # Remember, addresses don't include the bank!
            _, banked_addr = bank(tentative_addr)
            if matched_addr == banked_addr and asm_wd11e_addr == match.group(1):
                addresses['PokedexOrder'] = tentative_addr
                break
        else:
            raise CartDetectionError("Can't find Pokédex order")

        # This is assembly code that appears near the end of a function called
        # WaitForSoundToFinish.
        end_of_WaitForSoundToFinish = bytes.fromhex('afb6 23b6 2323 b6')
        try:
            idx = self.data.index(end_of_WaitForSoundToFinish)
        except ValueError:
            raise CartDetectionError("Can't find name array")
        # There are a couple more bytes in the function, but they involve an
        # address so they can't be searched for.  Red/Green/Blue have four;
        # Yellow has an extra 'and', which is annoying, but at least easy to
        # handle.
        start = idx + len(end_of_WaitForSoundToFinish)
        if self.data[start] == 0xA7:
            # Yellow; skip one more byte
            start += 1
        start += 4

        name_pointers = Array(7, ULInt16('dummy')).parse(self.data[start:start + 14])
        # One downside to the Game Boy memory structure is that banks are not
        # stored anywhere near their corresponding addresses, so the bank
        # numbers are hardcoded here.  They're fairly unlikely to change
        # between games.  Right?  Probably?
        addresses['MonsterNames'] = unbank(0x07, name_pointers[0])
        addresses['MoveNames'] = unbank(0x2C, name_pointers[1])
        # 2: UnusedNames  (unused, obviously)
        addresses['ItemNames'] = unbank(0x01, name_pointers[3])
        # 4: wPartyMonOT  (only useful while the game is running)
        # 5: wEnemyMonOT  (only useful while the game is running)
        addresses['TrainerNames'] = unbank(0x0E, name_pointers[6])

        return addresses

    def detect_game(self):
        """Given a cart image, return the game and language.

        This is a high-level interface; it prints stuff to stdout and raises
        exceptions.  Its two helpers do not.
        """
        # TODO raise, don't print to stdout
        # We have checksums for each of the games, but we also want to support
        # a heuristic so this same code can be used for trimmed carts,
        # bootlegs, fan hacks, corrupted carts, and other interesting variants.
        # Try both, and warn if they don't agree.
        game_c, language_c = self.detect_game_checksum()
        game_h, language_h = self.detect_game_heuristic()
        game = game_c or game_h
        language = language_c or language_h
        if game and language:
            print("Detected {filename} as {game}, {language}".format(
                filename=self.path.name, game=game, language=language))
        else:
            print("Can't figure out what game {filename} is!  ".format(
                filename=self.path.name), end='')
            if game:
                # TODO should probably be a way to override this
                print("It seems to be {}, but I can't figure out the language.".format(game))
            elif language:
                print("It seems to use {} text, but I can't figure out the version.".format(language))
            else:
                print("Nothing about it is familiar to me.")
            print("Bailing, sorry  :(")
            sys.exit(1)

        # Warn about a potentially bad checksum
        if not game_c or not language_c:
            log.warn(
                "Hmm.  I don't recognize the checksum for {}, but I'll "
                "continue anyway.",
                self.path.name)
        elif game_c != game_h or language_c != language_h:
            log.warn(
                "This is very surprising.  The checksum indicates that this "
                "game should be {}, {}, but I detected it as {}, {}.  Probably "
                "my fault, not yours.  Continuing anyway.",
                game_c, language_c, game_h, language_h)

        return game, language

    def detect_game_checksum(self):
        h = hashlib.md5()
        h.update(self.data)
        md5sum = h.hexdigest()

        return GAME_RELEASE_MD5SUM_INDEX.get(md5sum, (None, None))

    def detect_game_heuristic(self):
        # Okay, so, fun story: there's nothing /officially/ distinguishing the
        # games.  There's a flag in the cartridge header that's 0 for Japan and
        # 1 for anywhere other than Japan, but every copy of the game I've seen
        # has it set to anything other than 0 or 1, so that doesn't seem
        # particularly reliable.  I can't find any official and documented
        # difference.  It's as if they just changed the text, reassembled, and
        # called it a day.  In fact that's probably exactly what happened.

        # That makes life a little more difficult, so let's take this a step at
        # a time.  We can get the name of the game for free, at least, from the
        # cartridge header.
        self.stream.seek(0x100)
        header = game_boy_header_struct.parse_stream(self.stream)
        # Nintendo decided to lop off the last five bytes of the title for
        # other purposes /after/ creating the Game Boy, so the last three
        # letters of e.g.  POKEMON YELLOW end up in the manufacturer code.
        # Let's just, ah, put those back on.
        title = header.title + header.manufacturer_code.rstrip(b'\x00')
        if title == b'POKEMON RED':
            version = 'red'
        elif title == b'POKEMON GREEN':
            version = 'green'
        elif title == b'POKEMON BLUE':
            version = 'blue'
        elif title == b'POKEMON YELLOW':
            version = 'yellow'
        else:
            version = None

        # There's still a problem here: "red" might mean the Red from
        # Red/Green, released only in Japan; or the Red from Red/Blue, the pair
        # released worldwide, based on Japanese Blue.
        # Easy way to tell: Red and Green are the only games in the entire
        # series to use a half megabyte cartridge.  Any other game, even if
        # trimmed, will be just barely too big to fit in that size.
        if header.rom_size == 4:  # 512K -> Red/Green
            if version == 'red':
                game = 'jp-red'
            elif version == 'green':
                game = 'jp-green'
            else:
                # No other game is this size
                game = None
        elif header.rom_size == 5:  # 1M -> Red/Blue/Yellow
            if version == 'green':
                # Doesn't make sense; there was no green game bigger than 512K
                game = None
            elif version == 'red':
                game = 'ww-red'
            elif version == 'blue':
                # Can't know which Blue this is until we get the language
                game = None
            else:
                game = version
        else:  # ???
            return None, None

        # Now for language.  If the game is Japanese Red or Green, then it must
        # be in Japanese, so we're done.
        if game in ('jp-red', 'jp-green'):
            language = 'ja'
            return game, language

        # Otherwise, the only way to be absolutely sure is to find some text
        # and see what language it's in.
        self.stream.seek(self.addrs['ItemNames'])
        # Item 0 is MASTER BALL.  The first item with a different name in every
        # single language is item 4, TOWN MAP, so chew through five names.
        single_string_struct = PokemonCString('dummy')
        for _ in range(5):
            name = single_string_struct.parse_stream(self.stream)

        for language, expected_name in [
                ('de', 'KARTE'),
                ('en', 'TOWN MAP'),
                ('es', 'MAPA PUEBLO'),
                ('fr', 'CARTE'),
                ('it', 'MAPPA CITTÀ'),
                ('ja', 'タウンマップ'),
            ]:
            if name.decrypt(language) == expected_name:
                break
        else:
            # TODO raise probably
            language = None

        # Blue is a special case, remember
        if game is None and version == 'blue':
            if language is None:
                pass
            elif language == 'ja':
                game = 'jp-blue'
            else:
                game = 'ww-blue'

        # And done!
        return game, language

    ### From here it's all reified properties that extract on demand

    @reify
    def pokedex_order(self):
        """Maps internal Pokémon indices to the more familiar Pokédex order.

        Note that this maps to ONE LESS THAN National Dex number, so lists
        can be zero-indexed.
        """
        # Fetch the conversions between internal numbering and Pokédex order,
        # because that's a thing Gen 1 does, for some reason.
        self.stream.seek(self.addrs['PokedexOrder'])
        # I don't know exactly how many numbers are in this array, but it's
        # more than the number of Pokémon, because there are some MISSINGNO
        # gaps.  It's single bytes anyway, so I'm going to keep reading them
        # until I've seen every valid dex number.
        unseen_dex_numbers = set(range(1, self.NUM_POKEMON + 1))
        internal_to_dex_order = {}
        for index, dex_number in enumerate(self.stream.read(256), start=1):
            if dex_number == 0:
                continue
            internal_to_dex_order[index] = dex_number - 1
            unseen_dex_numbers.remove(dex_number)

            if not unseen_dex_numbers:
                break
        assert not unseen_dex_numbers
        return internal_to_dex_order

    @reify
    def max_pokemon_index(self):
        """Largest valid value of a Pokémon index.  Note that not every index
        between 0 and this number is necessarily a valid Pokémon; many of them
        are Missingno.  Only numbers that appear in `pokedex_order` are legit.
        """
        return max(self.pokedex_order)

    @reify
    def pokemon_names(self):
        """List of Pokémon names, in Pokédex order."""
        ret = [None] * self.NUM_POKEMON

        self.stream.seek(self.addrs['MonsterNames'])
        for index, pokemon_name in enumerate(Array(self.max_pokemon_index, pokemon_name_struct).parse_stream(self.stream), start=1):
            try:
                id = self.pokedex_order[index]
            except KeyError:
                continue
            ret[id] = pokemon_name.decrypt(self.language)

        return ret

    @reify
    def machine_moves(self):
        """List of move identifiers corresponding to TMs/HMs."""
        self.stream.seek(self.addrs['TechnicalMachines'])
        return Array(self.NUM_MACHINES, IdentEnum(ULInt8('move'), MOVE_IDENTIFIERS)).parse_stream(self.stream)

    @reify
    def pokemon_records(self):
        """List of pokemon_structs."""
        self.stream.seek(self.addrs['BaseStats'])
        print(self.stream.read(100).hex())
        records = Array(self.NUM_POKEMON - 1, pokemon_struct).parse_stream(self.stream)
        # Mew's data is, awkwardly, stored separately
        self.stream.seek(self.addrs['MewBaseStats'])
        records.append(pokemon_struct.parse_stream(self.stream))

        return records

    @reify
    def pokemon_evos_and_moves(self):
        """List of evos_moves_structs, including both evolutions and level-up
        moves.
        """
        ret = [None] * self.NUM_POKEMON
        self.stream.seek(self.addrs['EvosMovesPointerTable'])
        for index, pointer in enumerate(Array(self.max_pokemon_index, evos_moves_pointer).parse_stream(self.stream), start=1):
            try:
                id = self.pokedex_order[index]
            except KeyError:
                continue

            ret[id] = pointer.evos_moves
        return ret

    @reify
    def pokedex_entries(self):
        """List of pokedex_flavor_structs."""
        ret = [None] * self.NUM_POKEMON
        self.stream.seek(self.addrs['PokedexEntryPointers'])
        for index, pointer in enumerate(Array(self.max_pokemon_index, pokedex_flavor_pointer).parse_stream(self.stream), start=1):
            try:
                id = self.pokedex_order[index]
            except KeyError:
                continue

            ret[id] = pointer.pokedex_flavor.value

            record = pokemon_records_by_internal[index]
            pokedex_flavor = pointer.pokedex_flavor.value
            # TODO FUCKKKK IMPERIALLLLL
            #record.height = pokedex_flavor.height_feet * 12 + pokedex_flavor.height_inches
            #record.weight = pokedex_flavor.weight_pounds
            record.height = pokedex_flavor.height_decimeters
            record.weight = pokedex_flavor.weight_hectograms

            record.species = pokedex_flavor.species.decrypt(language)
            record.flavor_text = pokedex_flavor.flavor_text.decrypt(language)

    @reify
    def move_names(self):
        self.stream.seek(self.addrs['MoveNames'])
        return Array(NUM_MOVES, PokemonCString('move_name')).parse_stream(self.stream)



class RBYLoader:
    def __init__(self, *carts):
        self.carts = carts
        # TODO require all the same game

    def load(self):
        pass


# TODO would be slick to convert this to a construct...  construct
def bitfield_to_machines(bits, machine_moves):
    machines = []
    for i, move in enumerate(machine_moves, start=1):
        bit = bits & 0x1
        bits >>= 1
        if bit:
            machines.append(move)

    return machines


class WriterWrapper:
    def __init__(self, locus, language):
        self.locus = locus
        self.language = language

    def __setattr__(self, key, value):
        # TODO finish this...
        # 1. disallow reassigning an existing attr with a value
        setattr(self.locus, key, value)

    def __getattr__(self, key):
        return getattr(self.locus, key)


def main(root):
    # TODO does this need to take arguments?  or like, sprite mode i guess
    carts = []
    for filename in sys.argv[1:]:
        cart = RBYCart(Path(filename))
        carts.append(cart)

    root /= carts[0].game
    root.mkdir(exist_ok=True)

    #loader = RBYLoader(*carts)
    pokemons = OrderedDict([
        (POKEMON_IDENTIFIERS[id + 1], schema.Pokemon())
        for id in range(carts[0].NUM_POKEMON)
    ])
    for cart in carts:
        for id in range(cart.NUM_POKEMON):
            pokemon = pokemons[POKEMON_IDENTIFIERS[id + 1]]
            #writer = WriterWrapper(pokemon)
            writer = pokemon

            # TODO LOLLLL
            if 'name' not in writer.__dict__:
                writer.name = {}
            writer.name[cart.language] = cart.pokemon_names[id]

            record = cart.pokemon_records[id]

            # TODO put this in construct
            types = [record.type1]
            if record.type1 != record.type2:
                types.append(record.type2)

            writer.types = types
            writer.base_stats = {
                'hp': record.base_hp,
                'attack': record.base_attack,
                'defense': record.base_defense,
                'speed': record.base_speed,
                'special': record.base_special,
            }
            writer.growth_rate = record.growth_rate
            writer.base_experience = record.base_experience
            #writer.pokedex_numbers = dict(kanto=record.pokedex_number)

            # Starting moves are stored with the Pokémon; other level-up moves are
            # stored with evolutions
            level_up_moves = [
                {1: move}
                for move in record.initial_moveset
                # TODO UGH
                if move != '--'
            ]
            for level_up_move in cart.pokemon_evos_and_moves[id].level_up_moves:
                level_up_moves.append({
                    level_up_move.level: level_up_move.move,
                })
            # TODO LOLLLL
            if 'moves' not in writer.__dict__:
                writer.moves = {}
            writer.moves['level-up'] = level_up_moves
            writer.moves['machines'] = bitfield_to_machines(
                record.machines, cart.machine_moves)

            # Evolution
            # TODO alas, the species here is a number, because it's an internal id
            # and we switch those back using data from the game...
            evolutions = []
            for evo_datum in cart.pokemon_evos_and_moves[id].evolutions:
                evo = {
                    'into': POKEMON_IDENTIFIERS[cart.pokedex_order[evo_datum.evo_species] + 1],
                    'trigger': evo_datum.evo_trigger,
                    'minimum-level': evo_datum.evo_level,
                }
                # TODO insert the item trigger!
                evolutions.append(evo)
            writer.evolutions = evolutions

    with (root / 'pokemon.yaml').open('w') as f:
        f.write(Camel([schema.POKEDEX_TYPES]).dump(pokemons))


if __name__ == '__main__':
    # TODO yeah fix this up
    main(Path('pokedex/data'))