import * as DIR from "./directories.js";
import * as MAPS from "./maps.js";

// ----------------------------------------------------------------------

function main() {
    console.log("table_page_data", table_page_data);
    make_title();
    const parts = table_page_data.parts.reduce((accumulator, elt) => {
        accumulator[elt.type] = [...(accumulator[elt.type] || []), elt];
        return accumulator;
    }, {});
    show_parts(parts, "individual", table_page_data.subtype_id);
    show_parts(parts, "chain", table_page_data.subtype_id);
    // for (let part_data of table_page_data.parts)
    //     show_part(part_data, table_page_data.subtype_id);
    // $("body").append(`<pre>\n${JSON.stringify(table_page_data, null, 2)}\n</pre>`);
}

// ----------------------------------------------------------------------

function show_parts(parts, key, subtype_id) {
    for (var part of parts[key]) {
        const part_title_text = part_title(part, subtype_id);
        if (part_title_text)
            $("body").append(`<hr>\n<h3><a href="chain?subtype_id=${subtype_id}&chain_id=${part.chain_id}" target="_blank">${part_title_text} ${part.date} (${part.chain_id})</a></h3>`);
        switch (key) {
        case "individual":
            show_individual_table_maps(parts);
            break;
        case "chain":
            show_chain_maps(part, parts);
            break;
        }
    }
}

// ----------------------------------------------------------------------

function show_individual_table_maps(data, chain_data) {
    const table = $("<table></table>").appendTo("body");
    const tr_title = $("<tr class='title'></tr>").appendTo(table);
    const tr = $("<tr class='image'></tr>").appendTo(table);
    data.individual.forEach((data_individual) => {
        table_page_data.coloring.forEach((coloring, coloring_no) => {
            MAPS.td_title_append(tr_title, tr, MAPS.map_td_with_title(data_individual, "individual", coloring, coloring_no === 0));
        });
    });
    // procrustes
    data.individual.forEach((data_individual) => {
        data.chain.forEach((data_chain) => {
            for (let merge_type of ["incremental", "scratch"]) {
                MAPS.td_title_append(tr_title, tr, MAPS.pc_td_with_title(data_individual, "individual", data_chain, merge_type, table_page_data.coloring[0]));
            }
        });
    });
    // TODO: grid test
    // TODO: serum correlation widget
    // TODO: table widget
}

// ----------------------------------------------------------------------

function show_chain_maps(data_chain, data) {
    const table = $("<table></table>").appendTo("body");
    table_page_data.coloring.forEach((coloring, coloring_no) => {
        const tr_title = $("<tr class='title'></tr>").appendTo(table);
        const tr = $("<tr class='image'></tr>").appendTo(table);
        for (let merge_type of ["incremental", "scratch"]) {
            MAPS.td_title_append(tr_title, tr, MAPS.map_td_with_title(data_chain, merge_type, coloring, coloring_no === 0));
        }
        MAPS.td_title_append(tr_title, tr, MAPS.pc_td_with_title(data_chain, "incremental", data_chain, "scratch", coloring)); // pc incremental vs. scratch
        if (data.individual && data.individual[0]) {
            for (let merge_type of ["incremental", "scratch"]) {
                MAPS.td_title_append(tr_title, tr, MAPS.pc_td_with_title(data_chain, merge_type, data.individual[0], "individual", coloring));
            }
        }
        if (data_chain.mcb) {
            MAPS.td_title_append(tr_title, tr, MAPS.map_td_with_title(data_chain, "mcb", coloring, coloring_no === 0));
            if (data.individual && data.individual[0]) {
                MAPS.td_title_append(tr_title, tr, MAPS.pc_td_with_title(data_chain, "mcb", data.individual[0], "individual", coloring));
            }
            for (let merge_type of ["incremental", "scratch"]) {
                MAPS.td_title_append(tr_title, tr, MAPS.pc_td_with_title(data_chain, merge_type, data_chain, "mcb", coloring));
            }
        }
        for (let merge_type of ["incremental", "scratch"]) {
            // TODO: grid test
        }
    });
}

// ----------------------------------------------------------------------

function part_title(part_data, subtype_id) {
    switch (part_data.type) {
    case "individual":
        return null;
    case "chain":
        switch (part_data.chain_id[0]) {
        case "f":
            return "Chain"; // `<a href="chain?subtype_id=${subtype_id}&chain_id=${part_data.chain_id}" target="_blank">Chain</a>`;
        case "b":
            return "Backward chain"; // `<a href="chain?subtype_id=${subtype_id}&chain_id=${part_data.chain_id}" target="_blank">Backward chain</a>`;
        default:
            return "? Chain"; // `<a href="chain?subtype_id=${subtype_id}&chain_id=${part_data.chain_id}" target="_blank">? Chain</a>`;
        }

    }
    return null;
}

// ----------------------------------------------------------------------

function make_title() {
    let prefix = `${DIR.lab_to_display[table_page_data.lab]} ${DIR.subtype_to_display[table_page_data.subtype]}`;
    if (table_page_data.subtype === "h3")
        prefix += ` ${DIR.assay_to_display[table_page_data.assay]} ${table_page_data.rbc || ""}`;
    $("#title").html(`${prefix} ${table_page_data.table_date}`);
}

// ----------------------------------------------------------------------

$(document).ready(() => main());
