// Ported from AD acmacs-whocc/web/chains-202105/js/maps.js.
// Only difference from AD: make_link() points at this server's own /ace endpoint
// instead of the AD deployment-specific "/eu/results/chains-202105/..." path.

// ----------------------------------------------------------------------

export const IMAGE_SIZE = 800;

// ----------------------------------------------------------------------

export function make_request_data(data) {
    return Object.entries(data).map((en) => `${en[0]}=${encodeURIComponent(en[1])}`).join('&')
}

// ----------------------------------------------------------------------

export function make_link(data) {
    return `ace?ace=${encodeURIComponent(data.ace)}`;
}

// ----------------------------------------------------------------------

// returns {title: "text", td: "text"}
export function map_td_with_title(data, merge_type, coloring, save_chart) {
    const result = {};
    if (data[merge_type] && data[merge_type].ace) {
        const req = make_request_data({type: "map", ace: data[merge_type].ace, coloring: coloring, size: IMAGE_SIZE, save_chart: save_chart ? 1 : 0}); // save_chart must be number to properly convert to bool!
        const link = make_link({ace: data[merge_type].ace});
        result.title = `<td>${merge_type}<span class="map-title-space"></span><a href="ace?ace=${encodeURIComponent(data[merge_type].ace)}" download>ace</a> <a href="pdf?${req}" download>pdf</a><span class="map-title-space"></span>coloring:${coloring}</td>`;
        result.td = `<td><a href="${link}" target="_blank"><img src="png?${req}"></a></td>`;
    }
    return result.td ? result : null;
}

// ----------------------------------------------------------------------

// returns {title: "text", td: "text"}
export function pc_td_with_title(data1, merge_type1, data2, merge_type2, coloring) {
    const result = {};
    if (data1[merge_type1] && data1[merge_type1].ace && data2[merge_type2] && data2[merge_type2].ace) {
        const req = make_request_data({type: "pc", ace1: data1[merge_type1].ace, ace2: data2[merge_type2].ace, coloring: coloring, size: IMAGE_SIZE});
        result.title = `<td>pc ${merge_type1} vs. ${merge_type2}<span class="map-title-space"></span><a href="pdf?${req}" download>pdf</a><span class="map-title-space"></span>coloring:${coloring}</td>`;
        result.td = `<td><img src="png?${req}"></td>`;
    }
    return result.td ? result : null;
}

// ----------------------------------------------------------------------

export function td_title_append(tr_title, tr, to_append) {
    if (to_append) {
        tr_title.append(to_append.title);
        tr.append(to_append.td);
    }
}

// ----------------------------------------------------------------------
