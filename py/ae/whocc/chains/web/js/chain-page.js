import * as DIR from "./directories.js";
import * as MAPS from "./maps.js";

// ----------------------------------------------------------------------

function main() {
    console.log("chain_page_data", chain_page_data);
    make_title();
    for (let part_data of chain_page_data.parts)
        show_part(part_data, chain_page_data.subtype_id);
}

// ----------------------------------------------------------------------

function show_part(part_data, subtype_id) {
    const part_title_text = part_title(part_data, subtype_id);
    if (part_title_text)
        $("body").append(`<hr>\n<h3>${part_title_text}</h3>`);
    show_maps(part_data);
}

// ----------------------------------------------------------------------

function show_maps(data) {
    const table = $("<table></table>").appendTo("body");
    chain_page_data.coloring.forEach((coloring, coloring_no) => {
        const tr_title = $("<tr class='title'></tr>").appendTo(table);
        const tr = $("<tr class='image'></tr>").appendTo(table);
        for (let merge_type of ["incremental", "scratch", "individual", "mcb"]) {
            const td_title = MAPS.map_td_with_title(data, merge_type, coloring, coloring_no === 0);
            if (td_title) {
                tr_title.append(td_title.title);
                tr.append(td_title.td);
            }
        }
        // TODO: pc incremental vs. scratch
        for (let merge_type of ["incremental", "scratch"]) {
            // TODO: grid test
        }
    });
}

// ----------------------------------------------------------------------

function part_title(part_data, subtype_id) {
    return `<a href="table?subtype_id=${subtype_id}&date=${part_data.date}" target="_blank">${part_data.step} ${part_data.date}</a>`;
}

// ----------------------------------------------------------------------

function make_title() {
    let prefix = `${DIR.lab_to_display[chain_page_data.lab]} ${DIR.subtype_to_display[chain_page_data.subtype]}`;
    if (chain_page_data.subtype === "h3")
        prefix += ` ${DIR.assay_to_display[chain_page_data.assay]} ${chain_page_data.rbc || ""}`;
    const dates = `${chain_page_data.parts[chain_page_data.parts.length - 1].date}-${chain_page_data.parts[0].date}`;
    $("#title").html(`${prefix}${chain_page_data.type}: ${dates} ${chain_page_data.parts.length} tables (${chain_page_data.chain_id})`);
}

// ----------------------------------------------------------------------

$(document).ready(() => main());
