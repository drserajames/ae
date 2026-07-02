const sSubtypeOrder = ["h1pdm", "h3-hint", "h3-neut", "h3-hi", "bvic", "byam"];
const sLabOrder = ["cdc", "cnic", "crick", "niid", "vidrl"]
const sToday = new Date();

import * as DIR from "./directories.js";

// ----------------------------------------------------------------------

function show_subtype_tabs() {
    // console.log(index_subtypes);
    // split_subtypes(index_subtypes);
    // sort split_subtypes keys
    // index_subtypes = sort_subtypes(index_subtypes); // {subtype-assay: {lab: [entry]}}
    const subtype_tabs = $("<div class='subtype-tabs'></div>").appendTo("body");
    const tablinks = $("<div></div>").addClass("tablinks").prependTo(subtype_tabs);
    for (let subtype_assay of sSubtypeOrder) {
        if (index_subtypes[subtype_assay]) {
            const title = DIR.subtype_title[subtype_assay];
            const tabcontent = $("<div><table class='labs'><tr class='labs'><th></th></tr></table></div>")
                  .addClass("tabcontent")
                  .append(`<div class='loading-message'>Loading ${title}, please wait</div>`)
                  .appendTo(subtype_tabs);
            load_subtype_tab_data(tabcontent, index_subtypes[subtype_assay]);
            const button = $("<button></button>")
                  .addClass("tablink")
                  .attr("id", `button-${subtype_assay}`)
                  .html(title)
                  .on("click", ev => {
                      subtype_tabs.children(".tabcontent").each((_, tc) => tc.style.display = "none");
                      subtype_tabs.find(".tablink").each((_, tl) => tl.classList.remove("active"));
                      tabcontent.show();
                      ev.currentTarget.classList.add("active");
                  }).appendTo(tablinks);
        }
    }
    $(`#button-${sSubtypeOrder[0]}`).click();
}

// ----------------------------------------------------------------------

function api(url, callback) {
    $.getJSON(url, (response) => {
        if (response.ERROR)
            console.error(response.ERROR, response.tb || response);
        else
            callback(response);
    });
}

// ----------------------------------------------------------------------

function load_subtype_tab_data(tabcontent, subtype_data) {
    add_years(tabcontent.find("table.labs"), sToday.getFullYear() - 1);
    for (let lab of sLabOrder) {
        const en = subtype_data[lab];
        if (en) {
            for (let en of subtype_data[lab]) {
                api(`api/subtype-data/?subtype_id=${en.id}`, (data) => {
                    console.log(data);
                    const years = Object.keys(data.tables).sort()
                    add_years(tabcontent.find("table.labs"), Object.keys(data.tables).sort()[0]);
                    for (let year in data.tables) {
                        // console.log("year", year);
                        for (let month in data.tables[year]) {
                            // console.log(year, month, data.tables[year][month]);
                            data.tables[year][month].sort((en1,en2) => en2.date.localeCompare(en1.date));
                            for (let en of data.tables[year][month]) {
                                tabcontent.find(`tr[year-month='${year}-${month}'] td[lab='${lab}'] ul`).append(`<li><a href="table?subtype_id=${data.subtype_id}&date=${en.date}" target="_blank">${en.date}</a></li>`)
                            }
                        }
                    }
                    tabcontent.find(".loading-message").remove();
                });
            }
        }
    }
}

// ----------------------------------------------------------------------

function add_years(tbody, first) {

    const year_header = function(year, add_year_separator) {
        if (add_year_separator)
            tbody.append(`<tr class='year-separator'><td colspan=${sLabOrder.length + 1}><div></div></td></tr>`)
        const tr = $(`<tr year='${year}'><td>${year}</td></tr>`).appendTo(tbody);
        for (let lab of sLabOrder)
            tr.append(`<td class='lab-name'>${DIR.lab_to_display[lab]}</td>`);
    };

    for (let year = sToday.getFullYear(); year >= first; --year) {
        if (!tbody.find(`tr[year=${year}]`).length) {
            year_header(year, true); // year != sToday.getFullYear());
            const months = (year === sToday.getFullYear() ? [...Array(sToday.getMonth() + 1).keys()] : [...Array(12).keys()]).map(x => ++x).reverse();;
            for (let month of months) {
                const month2 = month.toLocaleString('en-US', {minimumIntegerDigits: 2, useGrouping:false})
                const tr = $(`<tr year-month='${year}-${month2}'><td month='${month2}'>${DIR.month_name[month]}</td></tr>`).appendTo(tbody);
                for (let lab of sLabOrder)
                    tr.append(`<td lab='${lab}'><ul></ul></td>`);
            }
        }
    }
}

// ----------------------------------------------------------------------

function subtype_tab_title(subtype_data) {
    if (subtype_data.subtype === "h3")
        return `${dir_subtype_to_display[subtype_data.subtype]} ${dir_assay_to_display[dir_assay_to_assay[subtype_data.assay]]}`;
    else
        return dir_subtype_to_display[subtype_data.subtype];
}

function split_subtypes(subtypes) {
    const subtype_assays = {};
    for (let subtype_data of subtypes) {
        const subtype_assay = subtype_data.subtype + "-" + dir_assay_to_assay[subtype_data.assay];
        if (!subtype_assays[subtype_assay])
            subtype_assays[subtype_assay] = [subtype_data];
        else
            subtype_assays[subtype_assay].push(subtype_data);
    }
    return subtype_assays;
}


function sort_subtypes(subtypes) {
    const subtype_order = ["h1pdm", "h3", "bvic", "byam"];
    const assay_order = ["hint", "neut", "hi"];
    const rank = (subtype_data) => subtype_order.indexOf(subtype_data.subtype) * 100 + assay_order.indexOf(subtype_data.assay);
    return subtypes.sort((en1, en2) => { return rank(en1) - rank(en2); });
}

// ----------------------------------------------------------------------

$(document).ready(() => show_subtype_tabs());
