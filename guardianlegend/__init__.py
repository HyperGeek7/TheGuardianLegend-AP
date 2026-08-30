from math import floor
from typing import List, Dict, Tuple, Optional, Any, Sequence

import settings
from BaseClasses import ItemClassification, Region, Tutorial
from worlds.AutoWorld import WebWorld, World
from .Items import TGLItem, TGLItemData, item_table, event_item_table, get_item_count
from .Locations import (TGLLocation, TGL_LOCID_BASE, TGL_LOCID_BONUS_GENERIC, location_table, location_table_generic,  
                        event_location_table, location_address_lookup, get_generic_locations_by_id, safety_locations)
from .Options import TGLOptions
from .Regions import create_regions
from .Rules import set_rules
from .Map import TGLMap
from .Rom import generate_output, ROM_HASH
from .Client import TGLClient


class TGLWebWorld(WebWorld):
    theme = "grass"
    tutorials = [
        Tutorial(
            tutorial_name="Start Guide",
            description="A guide to playing The Guardian Legend (NES).",
            language="English",
            file_name="tgl_guide_en.md",
            link="guide/en",
            authors=["CoreZero"]
        )
    ]


class TGLSettings(settings.Group):
    class RomFile(settings.UserFilePath):
        """File name of the TGL EN rom"""
        description = "The Guardian Legend ROM File"
        copy_to: Optional[str] = "Guardian Legend, The (USA).nes"
        md5s = [ROM_HASH,]

        def browse(self: settings.T,
                   filetypes: Optional[Sequence[Tuple[str, Sequence[str]]]] = None,
                   **kwargs: Any) -> Optional[settings.T]:
            if not filetypes:
                file_types = [("NES", [".nes"])]
                return super().browse(file_types, **kwargs)
            else:
                return super().browse(filetypes, **kwargs)

    rom_file: RomFile = RomFile(RomFile.copy_to)


class TGLWorld(World):
    """THE GUARDIAN LEGEND (NES 1988, Irem/Compile)"""

    game = "The Guardian Legend"
    web = TGLWebWorld()
    options_dataclass = TGLOptions
    options: TGLOptions
    tgl_random_map: Optional[TGLMap]
    tgl_random_locations: Optional[Dict[int, Tuple[int, int, int]]]
    settings: TGLSettings
    
    # combining Dicts like this is Py 3.9+ apparently...
    location_name_to_id = ({name: data.code for name, data in location_table.items()}
                           | {name: data.code for name, data in location_table_generic.items()}
                           | {name: data.code for name, data in safety_locations.items()})
    item_name_to_id = {name: data.code for name, data in item_table.items()}
                           #| {name: data.code for name, data in safety_key_table.items()})

    def generate_early(self) -> None:
        # If map rando option is set, need to randomize map here and pull out item location info
        if self.options.randomize_map:
            self.tgl_random_map = TGLMap()
            self.tgl_random_map.randomizeMap(self)
            #self.tgl_random_map.print_maps() # NOTE: For testing only, could be a logging option?
            # generic location ID as key
            # original location ID and the XY coordinates (for entrance hints) as data. 
            self.tgl_random_locations = self.tgl_random_map.get_randomized_item_locations()
            # NOTE: Test info - list of generate random location IDs
            #print("")
            #print(self.tgl_random_locations)
            #print("")
        
        #if self.options.use_safety_bypass_items:
            # Because this can add an arbitrary number of items to the pool,
            # we need to do some double-checks to ensure we can generate.

        #    if self.options.safety_bypass_requirement > self.options.safety_bypass_count:
        #        raise Exception("Can't ")

    # In order to know which location IDs to send in map rando, client needs a Dict of RAM bitflags to location IDs
    def fill_slot_data(self) -> Dict[str, Any]:
        # NOTE:
        #  Probably can/should switch the random map data to key on original location name
        # Use Location table with bitflags to populate table with gen locids
        # Send that dict (bitflag to gen locid) to slot data for client
        # Unfortunately slot_data cannot have tuple keys, so will convert to string first
        slot_data: Dict[str, Any] = {}
        slot_data["randomized_map"] = self.options.randomize_map.value
        location_ids: Dict[str, int] = {}
        if self.options.randomize_map:
            for code, data in self.tgl_random_locations.items():
                # If this is a bonus location, skip it because it has no associated bitflag
                # Corridor bonus ids are the highest so just check this ID is lower
                if (code < TGL_LOCID_BONUS_GENERIC):
                    bitflag: Tuple[int, int] = location_address_lookup[data[0]]
                    bitflag_str = f"{bitflag[0]},{bitflag[1]}"
                    location_ids[bitflag_str] = code
        slot_data["randomized_location_ids"] = location_ids
        return slot_data

    def create_item(self, name: str) -> TGLItem:
        #if self.options.use_safety_bypass_items and name in safety_key_table:
        #    data = safety_key_table[name]
        #else:
        data = item_table[name]
        return TGLItem(name, data.classification, data.code, self.player)
    
    def create_event(self, name: str) -> TGLItem:
        data = event_item_table[name]
        return TGLItem(name, data.classification, data.code, self.player)

    def create_regions(self):
        # For map rando, we have to grab which locations were used from the Map data and build the region list
        # Otherwise, we can just use the default location Dict
        random_location_list: List[str] = []
        if self.options.randomize_map:
            random_location_list.extend(get_generic_locations_by_id(list(self.tgl_random_locations.keys())))    
        create_regions(self.multiworld, self.player, random_location_list, self.options.use_safety_bypass_items)
        self._place_events()

    def _place_events(self):
        # Place "Corridor" items on "Corridor" event locations for Victory condition
        for locname, locdata in event_location_table.items():
            self.multiworld.get_location(locname, self.player).place_locked_item( 
                self.create_event(locname + " Cleared"))

    def set_rules(self):
        set_rules(self.multiworld, self.player, self.options)

    def get_filler_item_name(self) -> str:
        if not self.options.use_safety_bypass_items:
            return "Enemy Eraser"

        item_distribution = self.options.item_distribution.value
        eraser_count = get_item_count("Enemy Eraser", item_distribution, self.options)
        pack_count = get_item_count("Energy Pack", item_distribution, self.options)
        ratio = eraser_count / (eraser_count + pack_count)
        
        if self.random.random() < ratio:
            return "Enemy Eraser"
        return "Energy Pack"

    def create_items(self) -> None:
        item_pool: List[TGLItem] = []
        loc_count = len(self.multiworld.get_unfilled_locations(self.player))

        for name, data in item_table.items():
            if self.options.use_safety_bypass_items and data.classification == ItemClassification.filler:
                # The bypass items mess with the count of items in the pool in a way that I'm finding
                # kind of hard to reconcile with the hard-coded counts. My solution is to ignore the hard-
                # coded counts for items classified as filler (energy packs and enemy erasers) and then
                # add them back to any left over slots in roughly the same ratio as counts define.

                continue
            if self.options.item_distribution.value == 0:
                # Vanilla item distribution saved in table because of weirdness with counts
                quantity = data.max_quantity
                item_pool += [self.create_item(name) for _ in range(0, quantity)]
            else:
                # Call helper function to determine item counts
                quantity = get_item_count(name, self.options.item_distribution.value, self.options)
                item_pool += [self.create_item(name) for _ in range(0, quantity)]

        if self.options.use_safety_bypass_items:
            empty_count = loc_count - len(item_pool)
            item_distribution = self.options.item_distribution.value
            eraser_count = get_item_count("Enemy Eraser", item_distribution, self.options)
            pack_count = get_item_count("Energy Pack", item_distribution, self.options)
            ratio = eraser_count / (eraser_count + pack_count)
            eraser_count = floor(empty_count * ratio)
            item_pool += [self.create_item("Enemy Eraser") for _ in range(eraser_count)]
            item_pool += [self.create_item("Energy Pack") for _ in range(empty_count - eraser_count)]
        else:
            # Top up the pool, just in case I've borked something.
            empty_count = loc_count - len(item_pool)
            item_pool += [self.create_filler() for _ in range(empty_count)]

        self.multiworld.itempool += item_pool

    # Put the XY coordinates for locations in Entrance data, if map rando is on
    def extend_hint_information(self, hint_data: Dict[int, Dict[int, str]]) -> None:
        if self.options.randomize_map:
            hint_data.update({self.player: {}})
            for loc, data in self.tgl_random_locations.items():
                hint_data[self.player][loc] = f"X{data[1]} Y{data[2]}"

    def generate_output(self, output_directory: str) -> None:
        generate_output(self, output_directory, self.options)
